"""The driving-model choice in the shape large-model hosts read: {"sha256": <ONNX sha256>, "displayName": <name>}.

A host that runs a large driving model off the device (for example Jetlink, MIT) identifies a model by the sha256 of
the ONNX it was built from, and reads a fork's choice from one JSON param of that shape. The agreed key, when this
branch later meets the Jetlink branch, is `JetlinkBigModel` (`KEY` below). An empty choice (the Default model, or a
model that cannot be named by an ONNX hash) means the param is removed. The host may write a newer choice back with
the same fields (plus an optional "ref"), so `entry_for_value` maps a value back to an installed model.

Pure functions only: nothing here reads or writes a param, imports a host package, or touches modeld. This branch
does not write `JetlinkBigModel` yet.
"""
from __future__ import annotations

import json

from openpilot.common.bogpilot_models import STOCK_ID, registry

# Agreed hook for a later merge with the Jetlink branch. This module still does not read or write it.
KEY = "JetlinkBigModel"
MAX_DISPLAY_NAME = 60


def value_for_entry(entry: registry.Entry | None) -> dict | None:
  """The param value for a chosen entry, or None (remove the param) when it cannot be named by an ONNX hash."""
  if entry is None or entry.builtin or entry.id == STOCK_ID or entry.problem:
    return None
  onnx = entry.onnx_sha256
  if not onnx or not registry.SHA_RE.match(onnx):
    return None
  name = " ".join(str(entry.name or entry.id).split())[:MAX_DISPLAY_NAME]
  return {"sha256": onnx, "displayName": name}


def encode(value: dict | None) -> str | None:
  """Text to store (None: remove the param). Stable key order so equal choices give equal bytes."""
  return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))


def parse_value(raw) -> dict | None:
  """{"sha256", "displayName", "ref"} from a stored value, or None for unset, unreadable or hash-less text."""
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  if isinstance(raw, str):
    try:
      raw = json.loads(raw) if raw.strip() else None
    except ValueError:
      return None
  if not isinstance(raw, dict):
    return None
  sha = raw.get("sha256")
  if not isinstance(sha, str) or not registry.SHA_RE.match(sha):
    return None
  name = raw.get("displayName")
  ref = raw.get("ref")
  return {"sha256": sha, "displayName": " ".join(name.split())[:MAX_DISPLAY_NAME] if isinstance(name, str) else "",
          "ref": ref if isinstance(ref, str) and ref else None}


def entry_for_value(raw, entries: list[registry.Entry]) -> registry.Entry | None:
  """The installed, readable entry whose manifest declares the value's ONNX hash; None if none (or several) match."""
  v = parse_value(raw)
  if v is None:
    return None
  hits = [e for e in entries if not e.builtin and not e.problem and e.onnx_sha256 == v["sha256"]]
  return hits[0] if len(hits) == 1 else None
