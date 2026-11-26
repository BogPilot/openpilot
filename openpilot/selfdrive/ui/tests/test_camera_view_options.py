"""Onroad Camera View: Auto / Standard / Wide only, Driver gone, a saved Driver reads as Auto, Auto is upstream 0.11.2,
and the reverse view and the Settings cabin preview do not depend on CameraView."""
import ast
import os
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_params as P
from openpilot.selfdrive.ui.bogpilot import camera_view as cv

REGISTERED = P.BOGPILOT_PARAMS["CameraView"][2]
UI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # openpilot/selfdrive/ui


def _src(*parts):
  return open(os.path.join(UI, *parts)).read()


def test_options_are_auto_standard_wide_with_the_stored_codes():
  assert cv.OPTIONS == {0: "Auto", 2: "Standard", 3: "Wide"}
  assert "Driver" not in cv.OPTIONS.values() and cv.LEGACY_DRIVER not in cv.OPTIONS


@pytest.mark.parametrize("raw, want", [
  ("0", cv.AUTO), ("2", cv.STANDARD), ("3", cv.WIDE), (b"3", cv.WIDE), (2, cv.STANDARD), ("2.0", cv.STANDARD),
  ("1", cv.AUTO), (b"1", cv.AUTO), (1, cv.AUTO),                        # saved Driver -> Auto
  (None, cv.AUTO), ("", cv.AUTO), ("x", cv.AUTO), ("4", cv.AUTO), ("-1", cv.AUTO), ("2.5", cv.AUTO), ("nan", cv.AUTO),
  (b"\xff", cv.AUTO),
])
def test_saved_values_map_safely(raw, want):
  assert cv.normalize(raw) == want


def test_metadata_offers_no_driver_and_keeps_the_codes():
  tree = ast.parse(_src("bogpilot", "toggle_metadata.py"))
  for node in ast.walk(tree):
    if isinstance(node, ast.Call) and any(k.arg == "param" and getattr(k.value, "value", None) == "CameraView"
                                          for k in node.keywords):
      kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg in ("button_options", "value_map")}
      break
  else:
    raise AssertionError("CameraView definition not found")
  assert kw["button_options"] == ["Auto", "Standard", "Wide"]
  assert kw["value_map"] == cv.OPTIONS


def _road_view_switch():
  """The real AugmentedRoadView._switch_stream_if_needed and its speed constants, taken from the source so the test runs
  without the visionipc / GL natives the module imports."""
  tree = ast.parse(_src("onroad", "augmented_road_view.py"))
  ns = {"NARROW_ROAD_CAM": "narrow", "WIDE_CAM": "wide", "camera_view": cv}
  for node in tree.body:
    if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] in (["WIDE_CAM_MAX_SPEED"], ["ROAD_CAM_MIN_SPEED"]):
      exec(compile(ast.Module([node], []), "arv", "exec"), ns)
    if isinstance(node, ast.ClassDef) and node.name == "AugmentedRoadView":
      fn = next(f for f in node.body if isinstance(f, ast.FunctionDef) and f.name == "_switch_stream_if_needed")
      exec(compile(ast.Module([fn], []), "arv", "exec"), ns)
  return SimpleNamespace(WIDE_CAM="wide", NARROW_ROAD_CAM="narrow", step=ns["_switch_stream_if_needed"],
                         WIDE_CAM_MAX_SPEED=ns["WIDE_CAM_MAX_SPEED"], ROAD_CAM_MIN_SPEED=ns["ROAD_CAM_MIN_SPEED"])


class _View:
  """Just what AugmentedRoadView._switch_stream_if_needed touches."""
  def __init__(self, arv, stream, wide=True):
    self.stream_type = stream
    self.available_streams = [arv.NARROW_ROAD_CAM] + ([arv.WIDE_CAM] if wide else [])
  def switch_stream(self, s):
    self.stream_type = s
  def _camera_view_store(self):
    return None   # no store -> Auto


def _sm(exp, v):
  return {"selfdriveState": SimpleNamespace(experimentalMode=exp), "carState": SimpleNamespace(vEgo=v)}


def test_auto_is_upstream_0112_speed_switching():
  arv = _road_view_switch()
  assert (arv.WIDE_CAM_MAX_SPEED, arv.ROAD_CAM_MIN_SPEED) == (5.0, 10.0)   # upstream 0.11.2, 11 mph / 22 mph
  step = arv.step
  W, N = arv.WIDE_CAM, arv.NARROW_ROAD_CAM
  for start in (N, W):
    for v, want in ((0.0, W), (4.99, W), (5.0, start), (7.5, start), (10.0, start), (10.01, N), (30.0, N)):
      view = _View(arv, start)
      step(view, _sm(True, v))
      assert view.stream_type == want, (start, v)
    view = _View(arv, start)
    step(view, _sm(False, 0.0))
    assert view.stream_type == N, "narrow outside Experimental Mode"
  view = _View(arv, N, wide=False)
  step(view, _sm(True, 0.0))
  assert view.stream_type == N, "narrow when there is no wide stream"


def test_onroad_never_shows_the_cabin_camera_from_camera_view():
  # the only onroad cabin view is the reverse view; it is chosen by gear + QOLVisuals/DriverCamera, never CameraView
  for parts in (("onroad", "augmented_road_view.py"), ("layouts", "main.py"), ("bogpilot", "reverse_camera.py"),
                ("onroad", "reverse_camera_view.py")):
    assert "CameraView\"" not in _src(*parts) and "'CameraView'" not in _src(*parts), parts
  assert "VISION_STREAM_CABIN" not in _src("onroad", "augmented_road_view.py")
  rc = _src("bogpilot", "reverse_camera.py")
  assert 'get_bool("QOLVisuals")' in rc and 'get_bool("DriverCamera")' in rc


def test_settings_cabin_camera_preview_is_kept():
  dev = _src("layouts", "settings", "device.py")
  assert "CabinCameraDialog()" in dev and 'tr("PREVIEW")' in dev


class _Store:
  def __init__(self, **vals):
    self.vals = {k: str(v) for k, v in vals.items()}
    self.writes = []
  def get_bool(self, k):
    return self.vals.get(k, "0") in ("1", "True", "true")
  def get(self, k):
    if k == "boom":
      raise OSError
    return self.vals.get(k, REGISTERED if k == "CameraView" else "")   # unset -> what the manager stores on first boot
  def put(self, k, v):
    self.writes.append((k, v)); self.vals[k] = str(v)
  def invalidate(self, k=None):
    pass


@pytest.mark.parametrize("vals, want", [
  (dict(QOLVisuals=1, CameraView=0), cv.AUTO), (dict(QOLVisuals=1, CameraView=2), cv.STANDARD),
  (dict(QOLVisuals=1, CameraView=3), cv.WIDE), (dict(QOLVisuals=1, CameraView=1), cv.AUTO),
  (dict(QOLVisuals=0, CameraView=3), cv.AUTO), (dict(QOLVisuals=1, CameraView="junk"), cv.AUTO),
])
def test_selected_view(vals, want):
  assert cv.selected_view(_Store(**vals)) == want


def test_selected_view_never_raises():
  class Bad:
    def get_bool(self, k):
      raise OSError
  assert cv.selected_view(None) == cv.AUTO and cv.selected_view(Bad()) == cv.AUTO


def _view_with(arv, stream, store, wide=True):
  v = _View(arv, stream, wide)
  v._camera_view_store = lambda: store
  return v


@pytest.mark.parametrize("code, wide, want", [(2, True, "narrow"), (3, True, "wide"), (3, False, "narrow")])
def test_standard_and_wide_hold_one_stream_at_every_speed(code, wide, want):
  arv = _road_view_switch()
  for start in ("narrow", "wide") if wide else ("narrow",):
    for exp in (True, False):
      for v in (0.0, 4.0, 7.5, 12.0, 35.0):
        view = _view_with(arv, start, _Store(QOLVisuals=1, CameraView=code), wide)
        arv.step(view, _sm(exp, v))
        assert view.stream_type == want, (code, start, exp, v)


def test_saved_driver_runs_auto_onroad():
  arv = _road_view_switch()
  for v, want in ((0.0, "wide"), (30.0, "narrow")):
    view = _view_with(arv, "narrow" if want == "wide" else "wide", _Store(QOLVisuals=1, CameraView=1))
    arv.step(view, _sm(True, v))
    assert view.stream_type == want


def test_settings_row_offers_auto_standard_wide_under_qol_visuals():
  src = _src("layouts", "settings", "bogpilot_visuals.py")
  assert '("QOLVisuals", (("DriverCamera", ()), (CAMERA_KEY, ()), ("OnroadDistanceButton", ())))' in src
  assert "CV.OPTIONS.values()" in src and "Driver\"" not in src.split("CAMERA_KEY =")[1].split("def _store")[0]
  assert cv.CODES == (0, 2, 3) and [cv.button_index(c) for c in (0, 1, 2, 3, 9)] == [0, 0, 1, 2, 0]


# --- registered default: Auto (stock behavior) ---

def _openpilot_src(*parts):
  return open(os.path.join(os.path.dirname(os.path.dirname(UI)), *parts), encoding="utf-8").read()   # openpilot/


def test_registered_default_is_auto_everywhere_it_is_declared():
  assert REGISTERED == str(cv.AUTO) == "0" and P.BOGPILOT_PARAMS["CameraView"][4] == "0"
  assert '{"CameraView", {PERSISTENT, INT, "0"}}' in _openpilot_src("common", "params_keys_bogpilot.h")
  assert P.render_header() == _openpilot_src("common", "params_keys_bogpilot.h")
  assert "('CameraView', '0', 2, '0')," in _openpilot_src("selfdrive", "ui", "bogpilot", "bogpilot_defaults.py")
  assert '"CameraView": {\n    "declared_default": "0",' in _openpilot_src("selfdrive", "ui", "bogpilot",
                                                                            "phase3_system_settings_feature_specs.py")
  for rel in (("common", "bogpilot_params.py"), ("common", "params_keys_bogpilot.h"),
              ("selfdrive", "ui", "bogpilot", "bogpilot_defaults.py")):
    for line in _openpilot_src(*rel).splitlines():
      if '"CameraView"' in line or "'CameraView'" in line:
        assert '"3"' not in line and "'3'" not in line, (rel, line)


def test_fresh_install_resolves_to_auto():
  # nothing saved: the manager stores the registered default, which reads, shows and runs as Auto
  fresh = _Store(QOLVisuals=1)
  assert cv.normalize(REGISTERED) == cv.AUTO and cv.selected_view(fresh) == cv.AUTO
  assert cv.button_index(cv.normalize(fresh.get("CameraView"))) == 0
  arv = _road_view_switch()
  for v, want in ((0.0, "wide"), (30.0, "narrow")):
    view = _view_with(arv, "narrow" if want == "wide" else "wide", fresh)
    arv.step(view, _sm(True, v))
    assert view.stream_type == want, v
  assert fresh.writes == []


def test_both_settings_resets_write_auto():
  from openpilot.system.bogpilot import toggle_reset as tr
  assert "CameraView" in tr.RESET_KEYS
  assert tr.shipping_defaults()["CameraView"] == "0" and tr.reset_defaults()["CameraView"] == "0"


@pytest.mark.parametrize("saved, want", [("2", cv.STANDARD), ("3", cv.WIDE), (b"2", cv.STANDARD), (b"3", cv.WIDE)])
def test_saved_standard_and_wide_are_kept(saved, want):
  store = _Store(QOLVisuals=1, CameraView=saved.decode() if isinstance(saved, bytes) else saved)
  assert cv.normalize(saved) == want and cv.selected_view(store) == want
  assert store.vals["CameraView"] == str(int(saved)) and store.writes == []


@pytest.mark.parametrize("saved", ["1", b"1", 1])
def test_saved_driver_maps_to_auto_with_the_new_default(saved):
  store = _Store(QOLVisuals=1, CameraView=saved.decode() if isinstance(saved, bytes) else saved)
  assert cv.normalize(saved) == cv.AUTO and cv.selected_view(store) == cv.AUTO and store.writes == []


@pytest.mark.parametrize("saved", [None, "", "junk", "4", "-1", "2.5", "nan", b"\xff", "  "])
def test_garbage_or_missing_falls_back_to_auto(saved):
  assert cv.normalize(saved) == cv.AUTO
  store = _Store(QOLVisuals=1) if saved is None else _Store(QOLVisuals=1, CameraView=saved if isinstance(saved, str) else "x")
  assert cv.selected_view(store) == cv.AUTO and store.writes == []
