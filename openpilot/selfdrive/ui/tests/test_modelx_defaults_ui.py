"""AP1 Model X defaults (next build), UI side: alert volume defaults, the X pedal gauge regen scale, and the
Earlier, Gentler Regen Stops row on the X (only with its openpilot longitudinal opt-in). Model S rows prove the S is unchanged."""
from types import SimpleNamespace as NS

import pytest

from openpilot.selfdrive.car import ap1_runtime as runtime
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3

X, S, PREAP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


class Store:
  def __init__(self, **values):
    self.values = dict(values)

  def raw(self, key):
    return self.values.get(key)

  def put(self, key, value):
    self.values[key] = value


# ---- AP1 alert volume defaults ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("fp", [S, X])
def test_volume_defaults_s_and_x_unset_keys_only(fp):
  profile = {"AlertVolumeControl": "0", "EngageVolume": "101", "DisengageVolume": "101", "PromptVolume": "101"}
  store = Store(PromptVolume="60")                                     # a saved choice
  changed = runtime.apply_ap1_volume_defaults(NS(carFingerprint=fp), None, store, profile)
  assert set(changed) == {"AlertVolumeControl", "EngageVolume", "DisengageVolume"}
  assert store.values["PromptVolume"] == "60"
  assert runtime.apply_ap1_volume_defaults(NS(carFingerprint=fp), None, store, profile) == []


@pytest.mark.parametrize("fp", [PREAP, "TESLA_MODEL_3", "", None])
def test_volume_defaults_never_other_cars(fp):
  store = Store()
  assert runtime.apply_ap1_volume_defaults(NS(carFingerprint=fp), None, store, {"EngageVolume": "101"}) == []
  assert store.values == {}


def test_volume_profile_is_the_bogpilot_defaults():
  from openpilot.common.bogpilot_alert_volumes import AP1_VOLUME_PROFILE, BOGPILOT_VOLUME_DEFAULTS
  assert AP1_VOLUME_PROFILE == BOGPILOT_VOLUME_DEFAULTS
  assert runtime.AP1_VOLUME_PLATFORMS == frozenset({S, X})


# ---- Pedal gauge regen scale ------------------------------------------------------------------------------------------

def test_x_regen_peak_front_plus_rear_s_and_preap_stay_42():
  # trim profiles: the X full bar is front + rear (0x108 + 0x186), 71.6 kW measured; it was the rear-only 49 kW
  assert G3.regen_peak_kw(X) == G3.REGEN_PEAK_KW_AP1_X == 71.6
  assert G3.regen_peak_kw(S) == G3.REGEN_PEAK_KW_AP1_S == 42.0
  assert G3.regen_peak_kw(PREAP) == 42.0 and G3.regen_peak_kw("unknown") == G3.REGEN_PEAK_KW_DEFAULT == 42.0


def test_x_regen_bar_fills_on_the_x_scale():
  rpm = 3828.0                                                         # the X drive's peak-regen sample (34 mph)
  w = rpm * 2 * 3.141592653589793 / 60
  rear, front = -49.0e3 / w, -22.6e3 / w                               # 49 kW rear + 22.6 kW front = 71.6 kW
  assert G3.regen_power_fill(rear, rpm, X) == pytest.approx(49.0 / 71.6, abs=1e-3)                 # rear alone
  assert G3.regen_power_fill(rear, rpm, X, front_torque_nm=front, front_rpm=rpm) == pytest.approx(1.0, abs=1e-3)
  assert G3.regen_power_fill(rear, rpm, S) == 1.0                      # the S bar saturates at its own 42 kW
  half = rear * 21.0 / 49.0
  assert G3.regen_power_fill(half, rpm, X) == pytest.approx(21.0 / 71.6, abs=1e-3)
  assert G3.regen_power_fill(half, rpm, S) == pytest.approx(21.0 / 42.0, abs=1e-3)


def test_zero_torque_and_full_scale_constants_unchanged():
  assert G3.REGEN_FULLSCALE_NM == 116.0 and G3.ACCEL_FULLSCALE_NM == 200.0
  assert G3.REGEN_FULLSCALE_KW_AP1_X == G3.REGEN_FULLSCALE_KW_AP1_S == -55.0


# ---- Vehicle Controls: Earlier, Gentler Regen Stops row ---------------------------------------------------------------

def cp(fp, long, dashcam=False):
  return NS(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True):
  return pv.VehicleSettings(NS(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                            file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))


def test_regen_row_on_x_only_with_op_long_default_on_and_saved_value_kept(tmp_path):
  m = model(cp(X, True), tmp_path)
  assert m.visible(pv.REGEN) and m.enabled(pv.REGEN)
  assert m.read(pv.REGEN) is True                                      # no file: default on
  assert m.write(pv.REGEN, False) and (tmp_path / pv.REGEN).read_text() == "0" and m.read(pv.REGEN) is False
  assert m.write(pv.REGEN, True) and m.read(pv.REGEN) is True
  for other in (pv.RADAR, pv.IBOOSTER):
    assert not m.visible(other)                                        # still none of the Pre-AP only rows on the X
  assert m.visible(pv.CLUSTER)                                         # Dash Cluster Integration is shared with the Model S
  assert m.visible(pv.LONG)                                            # the Disable row is shared with the Model S


@pytest.mark.parametrize("car", [cp(X, False), cp(X, True, dashcam=True), None])
def test_regen_row_hidden_on_x_without_long_or_undetected(tmp_path, car):
  m = model(car, tmp_path)
  assert not m.visible(pv.REGEN) and not m.write(pv.REGEN, True) and not (tmp_path / pv.REGEN).exists()


def test_regen_row_model_s_unchanged(tmp_path):
  s = model(cp(S, True), tmp_path)
  assert s.visible(pv.REGEN) and s.read(pv.REGEN) is True and s.visible(pv.CLUSTER) and s.visible(pv.LONG)
  assert not model(cp(S, False), tmp_path).visible(pv.REGEN)
