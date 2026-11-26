"""Release gate: the committed libparams_c.so must match params_keys*.h, and every offroad alert must be a param.

Branches that ship a `prebuilt` marker never run SCons on the device, so the committed libparams_c.so is the only
key table the device has. If a key is added to params_keys.h without rebuilding the library, Params raises
UnknownKeyName at runtime. The offroad home iterates every entry in alerts_offroad.json, so a missing alert key
crashes the UI on every frame and the device never leaves the splash screen.

The library is loaded with ctypes and its own key list (params_keys_size / params_key_at) is compared against the
headers, so short keys the compiler builds inline are checked as reliably as long ones. The library is an aarch64
ELF on prebuilt branches; on any other host the library checks skip with a reason. The alert/header check runs
everywhere.
"""
import ctypes
import json
import os
import platform
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "openpilot/common/libparams_c.so"
HEADERS = (ROOT / "openpilot/common/params_keys.h", ROOT / "openpilot/common/params_keys_bogpilot.h")
OFFROAD_ALERTS = ROOT / "openpilot/selfdrive/selfdrived/alerts_offroad.json"

# Offroad alert keys that are deliberately not Params keys (read from another store by the widget).
NON_PARAM_ALERTS = {"BogPilot_ModelFallback"}

TYPES = {"STRING": 0, "BOOL": 1, "INT": 2, "FLOAT": 3, "TIME": 4, "JSON": 5, "BYTES": 6}
ENTRY = re.compile(r'^\s*\{"([A-Za-z0-9_]+)",\s*\{([^,]+),\s*([A-Z]+)(?:,\s*(.+?))?\}\},?\s*(?://.*)?$')
ELF_MACHINES = {183: "aarch64", 62: "x86_64"}


def header_keys():
  keys = {}
  for header in HEADERS:
    for line in header.read_text().splitlines():
      m = ENTRY.match(line)
      if not m:
        assert not re.match(r'^\s*\{"[A-Za-z0-9_]+",', line), f"unparsed key entry in {header.name}: {line.strip()}"
        continue
      name, _flags, type_name, default = m.groups()
      assert name not in keys, f"duplicate key {name}"
      assert type_name in TYPES, f"unknown type {type_name} for {name}"
      literal = None
      if default is not None:
        d = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', default.strip())
        literal = d.group(1).encode() if d else ...  # ... = computed default, compared by presence only
      keys[name] = (TYPES[type_name], literal)
  assert len(keys) > 100
  return keys


def lib_machine():
  with open(LIB, "rb") as f:
    head = f.read(20)
  if head[:4] != b"\x7fELF":
    return None
  return ELF_MACHINES.get(int.from_bytes(head[18:20], "little"), "unknown")


class ParamsBuffer(ctypes.Structure):
  _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


@pytest.fixture(scope="module")
def lib_params():
  if not LIB.exists():
    pytest.skip("no committed libparams_c.so (source build)")
  machine = lib_machine()
  if machine is not None and machine != platform.machine():
    pytest.skip(f"libparams_c.so is {machine}; this gate needs an {machine} host (AGNOS build container or device)")
  lib = ctypes.CDLL(str(LIB))
  lib.params_create.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
  lib.params_create.restype = ctypes.c_void_p
  lib.params_destroy.argtypes = [ctypes.c_void_p]
  lib.params_last_error.restype = ctypes.c_char_p
  lib.params_keys_size.argtypes = [ctypes.c_void_p]
  lib.params_keys_size.restype = ctypes.c_size_t
  lib.params_key_at.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
  lib.params_key_at.restype = ParamsBuffer
  lib.params_check_key.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
  lib.params_check_key.restype = ctypes.c_bool
  lib.params_get_key_type.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
  lib.params_get_key_type.restype = ctypes.c_int
  lib.params_get_default.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
  lib.params_get_default.restype = ParamsBuffer
  with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "params").encode()
    handle = lib.params_create(path, len(path))
    assert handle, lib.params_last_error()
    try:
      def text(buf):
        return None if not buf.data else ctypes.string_at(buf.data, buf.size)
      keys = {text(lib.params_key_at(handle, i)).decode() for i in range(lib.params_keys_size(handle))}
      yield lib, handle, keys, text
    finally:
      lib.params_destroy(handle)


def test_every_header_key_is_known_to_the_library(lib_params):
  _, _, lib_keys, _ = lib_params
  missing = sorted(set(header_keys()) - lib_keys)
  assert not missing, f"libparams_c.so is stale, rebuild it: {len(missing)} key(s) missing: {missing}"


def test_library_has_no_keys_the_headers_dropped(lib_params):
  _, _, lib_keys, _ = lib_params
  extra = sorted(lib_keys - set(header_keys()))
  assert not extra, f"libparams_c.so is stale, rebuild it: {len(extra)} key(s) no longer in the headers: {extra}"


def test_library_types_and_defaults_match_the_headers(lib_params):
  lib, handle, lib_keys, text = lib_params
  wrong = []
  for name, (key_type, default) in header_keys().items():
    if name not in lib_keys:
      continue
    k = name.encode()
    assert lib.params_check_key(handle, k), name
    got_type = lib.params_get_key_type(handle, k)
    got_default = text(lib.params_get_default(handle, k))
    if got_type != key_type:
      wrong.append(f"{name}: type {got_type} != {key_type}")
    if default is None and got_default is not None:
      wrong.append(f"{name}: library default {got_default!r}, headers have none")
    elif default is ... and got_default is None:
      wrong.append(f"{name}: library has no default")
    elif isinstance(default, bytes) and got_default != default:
      wrong.append(f"{name}: library default {got_default!r} != {default!r}")
  assert not wrong, "libparams_c.so is stale, rebuild it:\n" + "\n".join(wrong)


def test_every_offroad_alert_is_a_param():
  alerts = set(json.loads(OFFROAD_ALERTS.read_text())) - NON_PARAM_ALERTS
  missing = sorted(alerts - set(header_keys()))
  assert not missing, f"offroad alerts without a params_keys entry: {missing}"


def test_every_offroad_alert_is_known_to_the_library(lib_params):
  lib, handle, _, _ = lib_params
  alerts = sorted(set(json.loads(OFFROAD_ALERTS.read_text())) - NON_PARAM_ALERTS)
  missing = [a for a in alerts if not lib.params_check_key(handle, a.encode())]
  assert not missing, f"offroad alerts unknown to libparams_c.so (the offroad home would crash): {missing}"
