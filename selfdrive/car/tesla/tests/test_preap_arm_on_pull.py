"""Pre-AP panda arm-on-pull + matching userspace (host-safe source/unit tests)."""
from __future__ import annotations

from pathlib import Path

from cereal import car
from openpilot.selfdrive.car.tesla.preap.engagement import DoublePullEngagement, preap_steer_drop

ROOT = Path(__file__).resolve().parents[4]
T = car.CarState.ButtonEvent.Type


def _pull(e, t, brake=False):
  ev = car.CarState.ButtonEvent.new_message(type=T.setCruise, pressed=True)
  out = e.filter_button_events([ev], enabled=True, now_ms=t, brake_pressed=brake, cancel=False)
  ev2 = car.CarState.ButtonEvent.new_message(type=T.setCruise, pressed=False)
  return out + e.filter_button_events([ev2], enabled=True, now_ms=t + 50, brake_pressed=brake, cancel=False)


def test_safety_rising_edge_clears_cruise_engaged_prev():
  h = (ROOT / "panda/board/safety/safety_tesla_preap.h").read_text()
  assert "preap_lever_engage_prev" in h
  assert "cruise_engaged_prev = false" in h
  # Rising-edge clear sits inside the lever==2 / Drive / doors gate.
  idx = h.index("lever == 2")
  block = h[idx:idx + 500]
  assert "if (!preap_lever_engage_prev)" in block
  assert "cruise_engaged_prev = false" in block
  assert "pcm_cruise_check(true)" in block
  assert "SAFETY_ALLOUTPUT" not in h


def test_interface_enable_buttons_set_cruise_only():
  src = (ROOT / "selfdrive/car/tesla/interface.py").read_text()
  assert "enable_buttons=(ButtonType.setCruise,)," in src
  assert "ButtonType.accelCruise, ButtonType.decelCruise" not in src.split("TESLA_PREAP_MODELS")[1].split("else:")[0]


def test_single_pull_latches_lateral_without_enable():
  e = DoublePullEngagement()
  assert _pull(e, 1000) == [] and e.lat_only and not e.long_latched


def test_double_pull_requests_long():
  e = DoublePullEngagement()
  _pull(e, 1000)
  assert any(b.type == T.setCruise for b in _pull(e, 1200)) and not e.lat_only and e.long_latched


def test_brake_after_double_pull_keeps_lateral():
  e = DoublePullEngagement()
  _pull(e, 1000)
  _pull(e, 1200)
  e.filter_button_events([], enabled=True, now_ms=5000, brake_pressed=True, cancel=False)
  assert e.lat_only and not e.long_latched


def test_brake_after_single_pull_keeps_lateral():
  e = DoublePullEngagement()
  _pull(e, 1000)
  e.filter_button_events([], enabled=True, now_ms=5000, brake_pressed=True, cancel=False)
  assert e.lat_only


def test_cancel_clears_latch():
  e = DoublePullEngagement()
  _pull(e, 1000)
  e.filter_button_events([], enabled=True, now_ms=2000, brake_pressed=False, cancel=True)
  assert not e.lat_only and not e.long_latched


def test_steer_drop_matches_panda_conditions():
  assert preap_steer_drop(3, 1, 0) and preap_steer_drop(0, 0, 9)
  assert not preap_steer_drop(2, 1, 0) and not preap_steer_drop(0, 1, 9) and not preap_steer_drop(0, 0, 5)


def test_userspace_cancels_on_panda_drop_and_aol_uses_lat_only():
  cs = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  iface = (ROOT / "selfdrive/car/tesla/interface.py").read_text()
  card = (ROOT / "frogpilot/controls/frogpilot_card.py").read_text()
  assert "preap_steer_drop" in cs and "preap_panda_drop" in cs
  assert "buttonCancel" in iface and "preap_panda_drop" in iface
  assert "pedalCruiseLatOnly" in card


def test_lat_chime_events_are_defined_with_sounds():
  # Host mac cannot import events.py (msgq ipc_pyx.so is AGNOS). Source-gate instead.
  cereal = (ROOT / "cereal/custom.capnp").read_text()
  events = (ROOT / "selfdrive/controls/lib/events.py").read_text()
  controlsd = (ROOT / "selfdrive/controls/controlsd.py").read_text()
  assert "pedalLatEnabled @34" in cereal and "pedalLatDisabled @35" in cereal
  assert "FrogPilotEventName.pedalLatEnabled" in events
  assert "AudibleAlert.engage" in events.split("pedalLatEnabled")[1].split("pedalLatDisabled")[0]
  assert "AudibleAlert.disengage" in events.split("pedalLatDisabled")[1].split("pedalUnavailable")[0]
  assert "pedalLatEnabled" in controlsd and "pedalCruiseLatOnly" in controlsd
