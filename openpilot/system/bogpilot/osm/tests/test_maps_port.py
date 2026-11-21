"""Navigation > Maps port: params and defaults, nothing downloads without a selection, selection -> mapd download list,
mapd progress parsing, the stale-map gate during a download. No network, no mapd."""
import json

from openpilot.common import bogpilot_params as bp
from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm import supervisor as S
from openpilot.system.bogpilot.osm.downloads import DownloadController, parse_progress
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage


def test_params_registered_with_sane_defaults():
  P = bp.BOGPILOT_PARAMS
  assert P["MapsSelected"][:3] == ("PERSISTENT", "STRING", "")            # no maps selected
  assert P["PreferredSchedule"][:2] == ("PERSISTENT", "INT")
  assert P["LastMapsUpdate"][:3] == ("PERSISTENT", "STRING", None)        # Never
  for key in ("OSMDownloadProgress", "MapSpeedLimit", "NextMapSpeedLimit"):
    assert P[key][0] == "CLEAR_ON_MANAGER_START", key
  for key in ("OSMDownloadLocations", "OSMDownloadBounds"):
    assert key in P
  header = open(bp.HEADER_PATH, encoding="utf-8").read()
  for key in ("MapsSelected", "PreferredSchedule", "LastMapsUpdate", "OSMDownloadLocations", "OSMDownloadBounds", "OSMDownloadProgress"):
    assert f'{{"{key}", ' in header, key


class _Params:
  def __init__(self, data):
    self.data = data

  def get(self, key):
    return self.data.get(key)


def test_no_selection_means_no_process_and_no_download(tmp_path, monkeypatch):
  monkeypatch.setattr(S, "slc_enabled", lambda params: True)
  assert S.manager_condition(True, _Params({"MapsSelected": b""}), None) is False
  assert S.manager_condition(False, _Params({}), None) is False
  assert S.manager_condition(True, _Params({"MapsSelected": b'{"nations":[],"states":[]}'}), None) is False
  dl = DownloadController(MemParams(tmp_path / "d"), OsmStorage(tmp_path / "osm"))
  assert not dl.start(R.Selection((), ()))
  assert dl.jobs.load() is None


def test_selection_becomes_the_mapd_download_list(tmp_path):
  mem = MemParams(tmp_path / "d")
  dl = DownloadController(mem, OsmStorage(tmp_path / "osm"))
  sel = R.parse_selection('{"nations": ["DE", "ZZ"], "states": ["RI", "RI", "OH"]}')
  assert dl.start(sel)
  got = json.loads(mem.get_text("OSMDownloadLocations"))
  assert got == {"nations": ["DE"], "states": ["RI", "OH"]}                # unknown and duplicate codes dropped
  assert mem.get("OSMDownloadBounds") is None


def test_progress_parsing():
  assert parse_progress('{"total_files": 12, "downloaded_files": 5, "location_details": {}}') == (12, 5)
  assert parse_progress("") == (0, 0)
  assert parse_progress(None) == (0, 0)
  assert parse_progress("not json") == (0, 0)
  assert parse_progress('{"total_files": -3, "downloaded_files": "x"}') == (0, 0)
  assert parse_progress('[1, 2]') == (0, 0)


def test_slc_off_means_no_process_even_with_maps_selected(monkeypatch):
  monkeypatch.setattr(S, "ACTIVATION_POLICY", "default_on")
  sel = b'{"nations": [], "states": ["RI"]}'
  monkeypatch.setattr(S, "slc_enabled", lambda params: False)
  assert S.manager_condition(True, _Params({"MapsSelected": sel}), None) is False
  assert S.manager_condition(False, _Params({"MapsSelected": sel}), None) is False
  monkeypatch.setattr(S, "slc_enabled", lambda params: True)
  assert S.manager_condition(True, _Params({"MapsSelected": sel}), None) is True


def test_supervisor_wires_the_slc_rule_into_the_resumer_and_scheduler():
  import inspect
  src = inspect.getsource(S.main)
  assert "Resumer(mem, storage, allowed=lambda: downloads_allowed(store))" in src
  assert "UpdateScheduler(store" in src                               # the scheduler's own default allowed= is downloads_allowed
