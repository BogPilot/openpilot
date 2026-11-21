"""One-time carry-over of the Standstill Tap Speed from whole mph (AP1TapFromZeroMph) to m/s (AP1TapFromZeroMs)."""
from pathlib import Path

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.bogpilot import legacy_migration as lm
from openpilot.system.manager import bogpilot_startup as startup

OLD, NEW = "AP1TapFromZeroMph", "AP1TapFromZeroMs"


class DirParams:
  """Params-like object over a directory that knows the current BogPilot keys (so the old key is unknown)."""
  def __init__(self, root: Path, known=None):
    self.root = root
    root.mkdir(parents=True, exist_ok=True)
    self.known = set(BOGPILOT_PARAMS) if known is None else set(known)

  def get_param_path(self, key=""):
    return str(self.root / key)

  def all_keys(self):
    return [k.encode() for k in self.known]

  def check_key(self, key):
    if key not in self.known:
      raise KeyError(key)
    return key

  def get(self, key, *a, **k):
    self.check_key(key)
    p = self.root / key
    if not p.exists():
      return None
    text = p.read_bytes().decode()
    return float(text) if BOGPILOT_PARAMS[key][1] == "FLOAT" else text

  def put(self, key, value, block=False):
    self.check_key(key)
    # Params.put for a FLOAT key: str(float) (common/params.py PYTHON_2_CPP)
    (self.root / key).write_bytes((str(value) if not isinstance(value, bytes) else value.decode()).encode())

  def put_bool(self, key, value, block=False):
    self.put(key, "1" if value else "0")

  def remove(self, key):
    (self.root / key).unlink(missing_ok=True)

  def clear_unknown(self):
    """manager_init clear_all: files of unregistered keys are deleted."""
    for p in self.root.iterdir():
      if p.name not in self.known:
        p.unlink()

  def apply_defaults(self):
    for key in self.known:
      default = BOGPILOT_PARAMS[key][2]
      if default and not (self.root / key).exists():
        (self.root / key).write_text(default)


@pytest.fixture
def env(tmp_path, monkeypatch):
  files = tmp_path / "params_bogpilot"
  files.mkdir()
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(files))
  return DirParams(tmp_path / "params" / "d"), files


def test_registry_swaps_the_key():
  assert OLD not in BOGPILOT_PARAMS
  assert BOGPILOT_PARAMS[NEW] == ("PERSISTENT", "FLOAT", "6.7056", 1, "6.7056")


@pytest.mark.parametrize("n", range(5, 31))
def test_every_saved_mph_becomes_exact_ms(env, n):
  params, files = env
  (params.root / OLD).write_text(str(n))
  out = lm.migrate_tap_from_zero_ms(params, file_root=files)
  assert out == {"status": "migrated", "errors": []}
  assert params.get(NEW) == n * 0.44704   # bit for bit
  assert (params.root / OLD).read_text() == str(n)   # the old file is only read
  assert lm.tap_speed_migration_done(files)


def test_an_existing_ms_value_is_never_clobbered(env):
  params, files = env
  (params.root / OLD).write_text("20")
  params.put(NEW, 25 / 3.6)
  out = lm.migrate_tap_from_zero_ms(params, file_root=files)
  assert out["status"] == "kept" and params.get(NEW) == 25 / 3.6


@pytest.mark.parametrize("raw", ["", "  ", "foo", "15.5", "4", "31", "-5"])
def test_an_invalid_old_value_is_not_carried(env, raw):
  params, files = env
  (params.root / OLD).write_text(raw)
  out = lm.migrate_tap_from_zero_ms(params, file_root=files)
  assert out["status"] in ("invalid", "absent") and params.get(NEW) is None   # registered 15 mph default applies
  assert lm.tap_speed_migration_done(files)


def test_nothing_saved_writes_only_the_marker(env):
  params, files = env
  out = lm.migrate_tap_from_zero_ms(params, file_root=files)
  assert out["status"] == "absent" and params.get(NEW) is None and lm.tap_speed_migration_done(files)


def test_file_store_copy_is_used_when_params_never_had_it(env):
  params, files = env
  (files / OLD).write_text("22")
  assert lm.migrate_tap_from_zero_ms(params, file_root=files)["status"] == "migrated"
  assert params.get(NEW) == 22 * 0.44704


def test_old_library_without_the_new_key_writes_the_file_store(env):
  params, files = env
  params.known.discard(NEW)
  (params.root / OLD).write_text("12")
  assert lm.migrate_tap_from_zero_ms(params, file_root=files)["status"] == "migrated"
  assert float((files / NEW).read_text()) == 12 * 0.44704


def test_one_time_only(env):
  params, files = env
  (files / OLD).write_text("22")   # a stale file-store copy that clear_all never removes
  r = startup.before_clear(params, file_root=files)
  assert "tap-speed-migration:1" in r.events and params.get(NEW) == 22 * 0.44704
  params.remove(NEW)               # e.g. an archive restore back to "unset"
  r = startup.before_clear(params, file_root=files)
  r2 = startup.before_defaults(params, file_root=files, backup=lambda: None, reset=lambda *a, **k: None)
  assert params.get(NEW) is None and "tap-speed-migration:1" not in r.events + r2.events


def test_manager_order_keeps_the_saved_choice(env):
  """before_clear -> clear_all -> defaults: the saved 20 mph survives, the old file goes, the default never wins."""
  params, files = env
  (params.root / OLD).write_text("20")
  r = startup.before_clear(params, file_root=files)
  assert not [e for e in r.errors if e.startswith("tap-speed")]
  params.clear_unknown()
  params.apply_defaults()
  assert not (params.root / OLD).exists()
  assert params.get(NEW) == 20 * 0.44704


def test_fresh_install_gets_the_default(env):
  params, files = env
  startup.before_clear(params, file_root=files)
  params.clear_unknown()
  params.apply_defaults()
  assert params.get(NEW) == 6.7056


def test_failures_never_raise(env, monkeypatch):
  params, files = env
  (params.root / OLD).write_text("20")

  def boom(*a, **k):
    raise OSError("disk")
  monkeypatch.setattr(lm, "_write_new_value", boom)
  out = lm.migrate_tap_from_zero_ms(params, file_root=files)
  assert out["status"] == "error" and out["errors"] == [f"{OLD}: OSError"]
  assert not lm.tap_speed_migration_done(files)   # retried next boot
  r = startup.before_clear(params, file_root=files)
  assert any(e.startswith("tap-speed-migration") for e in r.errors)
