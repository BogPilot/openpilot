"""AP1 Model X visual profile: the AP1 Model S profile's screen, sidebar and theme values, once, saved values kept.

Also proves the AP1 Model S profile itself is unchanged and that no driving key reaches the X through this step.
"""
import pytest

from openpilot.common import bogpilot_ap1_profile as P

X, S, PREAP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


class FakeParams:
  def __init__(self, **vals):
    self.vals = {k: v for k, v in vals.items() if v is not None}
    self.puts = []

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value
    self.puts.append((key, block))

  def invalidate(self):
    pass


def table():
  return P._default_table()


def run(p, d):
  return P.apply_ap1x_visual_defaults_once(p, bogpilot_dir=d, refresh=False)


def test_profile_is_exactly_the_s_values_for_display_keys_only():
  params, files = P.ap1x_visual_profile()
  from openpilot.common.bogpilot_shipping_defaults import patch_ap1_file_profile, patch_ap1_param_profile
  s_params = patch_ap1_param_profile(dict(P.AP1_PARAM_PROFILE))
  s_files = patch_ap1_file_profile(dict(P.AP1_FILE_TOGGLE_PROFILE))
  assert params and all(params[k] == s_params[k] for k in params)
  assert files == {k: s_files[k] for k in ("SwapSpeedGraph", "DeveloperHUD")}
  assert set(params) <= set(P.AP1X_VISUAL_KEYS)
  driving = {"ConditionalExperimental", "CECurves", "CENavigationIntersections", "CustomPersonalities", "RelaxedFollow",
             "AccelerationProfile", "DecelerationProfile", "NewLongAPI", "SLCOverride", "SLCPriority1", "SLCPriority3",
             "SLCLookaheadHigher", "SLCLookaheadLower", "AlwaysOnLateral", "NNFFLite", "NudgelessLaneChange",
             "ShowSLCOffset", "PreferredSchedule", *P.AP1_SPEED_OFFSETS_MPH, *P.TUNING_LEVEL_KEYS}
  assert not (set(params) & driving), "no driving, lateral, speed or tuning key in the X visual profile"
  assert not (set(params) & set(P.NEVER_PROFILE_KEYS)) and not (set(params) & set(P._NEVER_PROFILE_VOLUME_KEYS))
  for key in ("SidebarMetrics", "DeveloperUI", "BorderMetrics", "OnroadDistanceButton", "DriverCamera", "CustomColors",
              "CustomIcons", "CustomSounds", "WheelIcon"):
    assert key in params


def test_fresh_x_gets_every_visual_value_once(tmp_path):
  t = table()
  p = FakeParams(CarModel=X, **{k: t[k] for k in P.AP1X_VISUAL_KEYS if k in t})   # registry defaults, like a fresh device
  written = run(p, tmp_path)
  params, files = P.ap1x_visual_profile()
  for key, value in params.items():
    if key in t:
      assert P.values_equal(p.vals[key], value), key
  assert all(block for _key, block in p.puts)                                       # persisted before the marker
  for key, value in files.items():
    assert (tmp_path / key).read_text() == value and key in written
  assert P.ap1x_visual_marker_path(tmp_path).exists()
  # one time only: a later change by the driver stays
  p.vals["SidebarMetrics"] = "0"
  assert run(p, tmp_path) == [] and p.vals["SidebarMetrics"] == "0"


def test_unset_keys_count_as_fresh(tmp_path):
  p = FakeParams(CarModel=X)
  written = run(p, tmp_path)
  params, _ = P.ap1x_visual_profile()
  t = table()
  for key, value in params.items():
    if key in t and not P.values_equal(t[key], value):
      assert key in written and p.vals[key] == value


def test_saved_values_are_kept(tmp_path):
  t = table()
  params, files = P.ap1x_visual_profile()
  changed = {}
  for key, value in params.items():
    if key in t:
      changed[key] = "custom-" + key                   # anything that is neither the registry default nor the profile value
  p = FakeParams(CarModel=X, **changed)
  (tmp_path / "SwapSpeedGraph").write_text("0")        # a saved file toggle
  written = run(p, tmp_path)
  assert written == [k for k in files if k != "SwapSpeedGraph"]
  assert all(p.vals[k] == v for k, v in changed.items()) and p.puts == []
  assert (tmp_path / "SwapSpeedGraph").read_text() == "0"


def test_no_stock_look_theme_migration_on_x(tmp_path):
  p = FakeParams(CarModel=X, CustomColors="stock", CustomIcons="stock", WheelIcon="stock", CustomSignals="none")
  run(p, tmp_path)
  assert (p.vals["CustomColors"], p.vals["CustomIcons"], p.vals["WheelIcon"], p.vals["CustomSignals"]) == (
    "stock", "stock", "stock", "none")
  assert not P.theme_marker_path(tmp_path).exists()


@pytest.mark.parametrize("car", [S, PREAP, "TESLA_MODEL_3", None])
def test_other_cars_untouched_and_get_no_marker(tmp_path, car):
  p = FakeParams(CarModel=car)
  assert run(p, tmp_path) == [] and p.puts == [] and not P.ap1x_visual_marker_path(tmp_path).exists()
  assert list(tmp_path.iterdir()) == []


def test_x_is_still_not_the_s_profile_platform(tmp_path):
  p = FakeParams(CarModel=X)
  assert not P.is_ap1(p) and P.is_ap1x_visual_platform(p)
  assert P.apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []   # the full S profile never runs on the X
  assert not P.marker_path(tmp_path).exists()


def test_model_s_profile_unchanged(tmp_path):
  # The S profile still writes its own full set (driving keys included) and never the X marker.
  p = FakeParams(CarModel=S)
  written = P.apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert "ConditionalExperimental" in written and "SidebarMetrics" in written
  assert not P.ap1x_visual_marker_path(tmp_path).exists()
  # Show Speed Limit Offset now controls the badge and the AP1 profile leaves it on
  assert P.AP1_PARAM_PROFILE["ShowSLCOffset"] == "1" and P.AP1_FILE_TOGGLE_PROFILE == {"SwapSpeedGraph": "1", "DeveloperHUD": "0"}


def test_toggle_reset_clears_the_x_marker_so_the_profile_is_offered_again(tmp_path):
  p = FakeParams(CarModel=X)
  run(p, tmp_path)
  assert P.ap1x_visual_marker_path(tmp_path).exists()
  P.clear_ap1_defaults_marker(tmp_path)
  assert not P.ap1x_visual_marker_path(tmp_path).exists()


def test_never_raises(tmp_path):
  class Broken(FakeParams):
    def get(self, key):
      raise RuntimeError("boom")
  assert run(Broken(CarModel=X), tmp_path) == []
