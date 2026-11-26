"""AP1 Model S and AP1 Model X get the same one-time AP1 profile: the same keys and values on a fresh device, saved values kept,
and the retired Model X only steps (visual profile, SLC only profile) no longer run on the X."""
import pytest

from openpilot.common import bogpilot_ap1_profile as P

X, S, PREAP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


class FakeParams:
  def __init__(self, **vals):
    self.vals = {k: v for k, v in vals.items() if v is not None}

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value

  def invalidate(self):
    pass


def _fresh(car, d):
  p = FakeParams(CarModel=car)
  written = P.apply_ap1_defaults_once(p, bogpilot_dir=d, refresh=False)
  files = {f.name: f.read_text() for f in d.iterdir() if f.is_file() and f.name != P.MARKER_NAME}
  return p, written, files


def test_fresh_x_gets_exactly_the_s_profile(tmp_path):
  s, s_written, s_files = _fresh(S, tmp_path / "s")
  x, x_written, x_files = _fresh(X, tmp_path / "x")
  assert s_written and sorted(x_written) == sorted(s_written)
  assert {k: v for k, v in x.vals.items() if k != "CarModel"} == {k: v for k, v in s.vals.items() if k != "CarModel"}
  assert x_files == s_files
  assert P.marker_path(tmp_path / "x").exists()
  for key in ("ConditionalExperimental", "CECurves", "CENavigationIntersections", "SidebarMetrics", "Offset1"):
    assert key in x_written, key


@pytest.mark.parametrize("car", [S, X])
def test_saved_values_kept_and_one_time_only(tmp_path, car):
  p = FakeParams(CarModel=car, SidebarMetrics="custom")
  P.apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert p.vals["SidebarMetrics"] == "custom"
  p.vals["CECurves"] = "0"
  assert P.apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == [] and p.vals["CECurves"] == "0"


def test_platform_helpers(monkeypatch):
  assert P.is_ap1(FakeParams(CarModel=S)) and P.is_ap1(FakeParams(CarModel=X))
  assert not P.is_ap1(FakeParams(CarModel=PREAP)) and not P.is_ap1(FakeParams())
  assert P.is_ap1_model_x(FakeParams(CarModel=X)) and not P.is_ap1_model_x(FakeParams(CarModel=S))
  monkeypatch.setattr(P, "_persistent_fingerprint", lambda params: X)
  assert P.is_ap1(FakeParams()) and P.is_ap1_model_x(FakeParams())


def test_retired_x_only_steps_are_gone(tmp_path):
  assert not hasattr(P, "apply_ap1x_visual_defaults_once") and not hasattr(P, "is_ap1x_slc_platform")
  assert P.LEGACY_SLC_PLATFORMS == frozenset({PREAP})
  assert P.apply_legacy_slc_defaults_once(FakeParams(CarModel=X), bogpilot_dir=tmp_path, refresh=False) == []
  assert not P.legacy_slc_marker_path(tmp_path).exists()


def test_toggle_reset_still_clears_an_old_x_visual_marker(tmp_path):
  P.ap1x_visual_marker_path(tmp_path).write_text("1\n")
  P.clear_ap1_defaults_marker(tmp_path)
  assert not P.ap1x_visual_marker_path(tmp_path).exists()


def test_startup_no_longer_runs_the_x_visual_step():
  from openpilot.system.manager import bogpilot_startup as BS
  src = open(BS.__file__).read()
  assert "apply_ap1x_visual_defaults_once" not in src and "apply_ap1_defaults_once(params, bogpilot_dir=directory)" in src
