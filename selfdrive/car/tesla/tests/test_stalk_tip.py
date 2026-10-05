"""AP1 cruise-stalk tip button (VSL_Enbl_Rq) unit tests. No PII."""

from openpilot.selfdrive.car.tesla.stalk_tip import (
  StalkTipDecision,
  parse_stalk_tip,
  tip_edge,
  tip_hold_cruise,
)


def test_tip_edge_requires_previous_and_change():
  assert tip_edge(None, None) is False
  assert tip_edge(1, None) is False
  assert tip_edge(None, 0) is False
  assert tip_edge(0, 0) is False
  assert tip_edge(1, 1) is False
  assert tip_edge(1, 0) is True
  assert tip_edge(0, 1) is True
  assert tip_edge(1.0, 0.0) is True
  assert tip_edge(2, 0) is False
  assert tip_edge("x", 0) is False


def test_parse_stalk_tip_first_sample_not_a_press():
  first = parse_stalk_tip(0, None)
  assert first == StalkTipDecision(pressed=False, vsl=0)
  second = parse_stalk_tip(0, first)
  assert second.pressed is False
  assert second.vsl == 0


def test_parse_stalk_tip_toggle_is_one_press_each_way():
  state = parse_stalk_tip(0, None)
  up = parse_stalk_tip(1, state)
  assert up.pressed is True and up.vsl == 1
  held = parse_stalk_tip(1, up)
  assert held.pressed is False and held.vsl == 1
  down = parse_stalk_tip(0, held)
  assert down.pressed is True and down.vsl == 0
  # Missing sample keeps last VSL, not a press.
  missing = parse_stalk_tip(None, down)
  assert missing.pressed is False and missing.vsl == 0


def test_tip_hold_cruise_starts_on_tip_while_enabled():
  assert tip_hold_cruise(False, True, True, 0, False, False) is True
  assert tip_hold_cruise(False, True, False, 0, False, True) is True
  assert tip_hold_cruise(False, True, False, 0, False, False) is False
  assert tip_hold_cruise(True, False, False, 0, False, False) is True


def test_tip_hold_cruise_clears_on_fwd_cancel_or_brake():
  assert tip_hold_cruise(True, False, False, 1, False, True) is False
  assert tip_hold_cruise(True, True, True, 1, False, True) is False
  assert tip_hold_cruise(True, False, False, 0, True, True) is False
  # Speed adjust (Spd 4) does not clear hold.
  assert tip_hold_cruise(True, False, False, 4, False, True) is True


def test_carstate_and_card_wire_tip():
  from pathlib import Path
  root = Path(__file__).resolve().parents[4]
  carstate = (root / "selfdrive/car/tesla/carstate.py").read_text()
  assert "parse_stalk_tip(" in carstate
  assert "tip_hold_cruise(" in carstate
  assert "VSL_Enbl_Rq" in carstate
  assert "self.stalk_tip" in carstate
  card = (root / "frogpilot/controls/frogpilot_card.py").read_text()
  assert "_apply_ap1_stalk_tip" in card
  assert "handle_experimental_mode(" in card
  assert "stalk_tip" in card
  # Forward-push cancel mapping stays SpdCtrlLvr 1 only.
  values = (root / "selfdrive/car/tesla/values.py").read_text()
  assert 'Button(car.CarState.ButtonEvent.Type.cancel, "STW_ACTN_RQ", "SpdCtrlLvr_Stat", [1])' in values
  assert "VSL_Enbl_Rq" not in values.split("BUTTONS")[1].split("class CarControllerParams")[0]


def test_panda_tip_ignore_window_present():
  from pathlib import Path
  root = Path(__file__).resolve().parents[4]
  safety = (root / "panda/board/safety/safety_tesla.h").read_text()
  assert "TESLA_AP1_TIP_CRUISE_IGNORE_US" in safety
  assert "tesla_ap1_tip_ignore_cruise_ts" in safety
  assert "vsl != tesla_ap1_vsl_prev" in safety
  # Must not skip pcm_cruise_check for non-AP1 / outside tip window.
  assert "pcm_cruise_check(cruise_engaged);" in safety
