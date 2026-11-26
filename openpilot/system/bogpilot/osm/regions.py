"""Map region catalog, selection and download-size model (0.9.7 Map Sources / MapsSelected).

Data: mapd v1.12.0 nation/us_state bounding boxes (MIT, pfeiferj/mapd) and the 0.9.7 FrogPilot region
grouping (MIT). Selection format is the 0.9.7 MapsSelected param: {"nations": [codes], "states": [codes]},
which mapd reads unchanged from OSMDownloadLocations.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).parent / "catalog"
GROUP_AREA_BOX_DEGREES = 2          # mapd v1.12.0 download.go: files are 2x2 degree cells
# Observed size of real cells (about 23 MB for two inland US cells, Nov 2026). Estimate only; ocean cells are tiny.
ESTIMATED_CELL_BYTES = 25 * 1024 * 1024
MAX_SELECTED_REGIONS = 200
# 0.9.7 saved Guam as "GU" but mapd keys it "GM": migrate saved selections instead of dropping them.
STATE_ALIASES = {"GU": "GM"}


@dataclass(frozen=True)
class Region:
  code: str
  name: str
  kind: str            # "nation" | "state"
  min_lat: float
  min_lon: float
  max_lat: float
  max_lon: float


@dataclass(frozen=True)
class Selection:
  nations: tuple[str, ...] = ()
  states: tuple[str, ...] = ()

  def is_empty(self) -> bool:
    return not (self.nations or self.states)

  def to_param(self) -> str:
    """0.9.7 MapsSelected JSON (Qt QJsonDocument::Compact style)."""
    return json.dumps({"nations": list(self.nations), "states": list(self.states)}, separators=(",", ":"))


def _load(name: str):
  with open(CATALOG_DIR / name, encoding="utf-8") as f:
    return json.load(f)


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Region]]:
  out = {"nation": {}, "state": {}}
  for kind, fname in (("nation", "nation_bounding_boxes.json"), ("state", "us_states_bounding_boxes.json")):
    for code, d in _load(fname).items():
      b = d["bounding_box"]
      out[kind][code] = Region(code, d["full_name"], kind, float(b["min_lat"]), float(b["min_lon"]),
                               float(b["max_lat"]), float(b["max_lon"]))
  return out


@lru_cache(maxsize=1)
def groups() -> dict[str, list[tuple[str, list[tuple[str, str]]]]]:
  """UI grouping: {"nations": [(label, [(code, name)])], "states": [...]}. Only codes mapd can download."""
  raw = _load("region_groups.json")
  cat = catalog()
  res = {}
  for key, kind in (("nations", "nation"), ("states", "state")):
    res[key] = [(g["label"], [(r["code"], r["name"]) for r in g["regions"] if r["code"] in cat[kind]]) for g in raw[key]]
  return res


def ungrouped_codes() -> dict[str, list[str]]:
  """Catalog codes that no UI group lists (and so could never be selected) - exposed for the tests."""
  g = groups()
  res = {}
  for key, kind in (("nations", "nation"), ("states", "state")):
    listed = {c for _, regs in g[key] for c, _ in regs}
    res[key] = sorted(set(catalog()[kind]) - listed)
  return res


def parse_selection(text) -> Selection:
  """Fail closed: bad JSON / wrong types / unknown codes give an empty or filtered selection, never an exception."""
  try:
    if isinstance(text, (bytes, bytearray)):
      text = text.decode("utf-8")
    d = json.loads(text) if text else {}
  except (ValueError, UnicodeDecodeError):
    return Selection()
  if not isinstance(d, dict):
    return Selection()
  cat = catalog()

  def clean(key, kind):
    v = d.get(key)
    if not isinstance(v, list):
      return ()
    seen, res = set(), []
    for c in v:
      if kind == "state" and isinstance(c, str):
        c = STATE_ALIASES.get(c, c)
      if isinstance(c, str) and c in cat[kind] and c not in seen:
        seen.add(c)
        res.append(c)
      if len(res) >= MAX_SELECTED_REGIONS:
        break
    return tuple(res)

  return Selection(clean("nations", "nation"), clean("states", "state"))


def adjusted_bounds(r: Region) -> tuple[int, int, int, int]:
  """Exact port of mapd v1.12.0 download.go adjustedBounds: (minLat, minLon, maxLat, maxLon) on the 2-degree grid."""
  g = GROUP_AREA_BOX_DEGREES
  min_lat = math.floor(r.min_lat / g) * g
  min_lon = math.floor(r.min_lon / g) * g
  max_lat = math.floor(r.max_lat / g) * g
  max_lon = math.floor(r.max_lon / g) * g
  if r.max_lat > max_lat:
    max_lat += g
  if r.max_lon > max_lon:
    max_lon += g
  return min_lat, min_lon, max_lat, max_lon


def cells_for_region(r: Region) -> list[tuple[int, int]]:
  min_lat, min_lon, max_lat, max_lon = adjusted_bounds(r)
  g = GROUP_AREA_BOX_DEGREES
  return [(i, j) for i in range(min_lat, max_lat, g) for j in range(min_lon, max_lon, g)]


def files_for_region(r: Region) -> int:
  """mapd countFilesForBounds (this is what OSMDownloadProgress.total_files counts, per region, with overlap)."""
  min_lat, min_lon, max_lat, max_lon = adjusted_bounds(r)
  g = GROUP_AREA_BOX_DEGREES
  return ((max_lat - min_lat) // g) * ((max_lon - min_lon) // g)


def resolve(sel: Selection) -> list[Region]:
  cat = catalog()
  return [cat["nation"][c] for c in sel.nations] + [cat["state"][c] for c in sel.states]


@dataclass(frozen=True)
class Estimate:
  total_files: int          # what mapd will report as total_files (overlapping cells counted per region)
  unique_cells: int
  est_bytes: int            # unique cells x ESTIMATED_CELL_BYTES (upper-bound-ish; downloads re-fetch overlaps)
  worst_bytes: int          # total_files x ESTIMATED_CELL_BYTES


def estimate(sel: Selection) -> Estimate:
  regs = resolve(sel)
  total = sum(files_for_region(r) for r in regs)
  cells = set()
  for r in regs:
    cells.update(cells_for_region(r))
  return Estimate(total, len(cells), len(cells) * ESTIMATED_CELL_BYTES, total * ESTIMATED_CELL_BYTES)


def cell_for_point(lat: float, lon: float) -> tuple[int, int]:
  g = GROUP_AREA_BOX_DEGREES
  return int(math.floor(lat / g)) * g, int(math.floor(lon / g)) * g
