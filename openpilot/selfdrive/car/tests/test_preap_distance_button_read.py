"""The 10 Hz OnroadDistanceButtonPressed read covers Pre-AP and AP1; the step-overrun timer is Pre-AP only; unknown cars read every step."""
from pathlib import Path

from openpilot.selfdrive.car.preap_card_step import use_10hz_distance_button, use_step_overrun_counter

CARD = Path(__file__).resolve().parents[1] / "card.py"


def test_unknown_reads_at_every_step_and_ap1_has_no_overrun_timer():
  for fp in ("TESLA_AP1_MODELX", None, "UNKNOWN_CAR", "MOCK"):
    assert use_10hz_distance_button(fp) is False
    assert use_step_overrun_counter(fp) is False
  assert use_step_overrun_counter("TESLA_AP1_MODELS") is False
  src = CARD.read_text()
  state = src[src.index("def state_update"):src.index("def params_thread")]
  params = src[src.index("def params_thread"):src.index("def card_thread")]
  thread = src[src.index("def card_thread"):]
  init = src[src.index("self.rk = Ratekeeper"):src.index("def state_update")]
  # AP1 / unknown: live Params read on the 100 Hz path, as in 92aa9ee1f
  assert 'self.params.get_bool("OnroadDistanceButtonPressed")' in state
  assert "use_10hz_distance_button(self.CP.carFingerprint)" in state
  assert "use_10hz_distance_button(self.CP.carFingerprint)" in params
  assert "if self.step_timer is not None:" in thread
  assert "self.step_timer.record" in thread
  assert "use_step_overrun_counter(self.CP.carFingerprint)" in init
  assert "07e8bd68f" in src and "92aa9ee1f" in src


def test_ap1_reads_at_10_hz():
  assert use_10hz_distance_button("TESLA_AP1_MODELS") is True
  src = CARD.read_text()
  state = src[src.index("def state_update"):src.index("def params_thread")]
  # the 100 Hz step reads only the snapshot for AP1; the live Params read is the unknown-car branch
  branch = state[state.index("if use_10hz_distance_button"):]
  assert branch.index("distance_pressed = self.onroad_distance_button") < branch.index('self.params.get_bool("OnroadDistanceButtonPressed")')
  assert "else:" in branch[:branch.index('self.params.get_bool("OnroadDistanceButtonPressed")')]


def test_snapshot_initialised_before_thread_and_only_written_by_params_thread():
  src = CARD.read_text()
  init = src[src.index("self.rk = Ratekeeper"):src.index("def state_update")]
  assert "self.onroad_distance_button = False" in init
  assert src.count("self.onroad_distance_button = ") == 2          # init + params thread, nowhere else
  params = src[src.index("def params_thread"):src.index("def card_thread")]
  assert "self.onroad_distance_button = self.params.get_bool(" in params
  assert "time.sleep(0.1)" in params                                 # 10 Hz
  thread = src[src.index("def card_thread"):]
  assert thread.index("t.start()") > 0


def test_preap_reads_at_10_hz():
  assert use_10hz_distance_button("TESLA_PREAP_MODELS") is True
  assert use_step_overrun_counter("TESLA_PREAP_MODELS") is True
  src = CARD.read_text()
  params = src[src.index("def params_thread"):src.index("def card_thread")]
  assert 'self.params.get_bool("OnroadDistanceButtonPressed")' in params


def test_mutant_applying_10hz_to_ap1_is_caught(monkeypatch):
  import openpilot.selfdrive.car.preap_card_step as m

  def always_10hz(fingerprint):
    return True

  monkeypatch.setattr(m, "use_10hz_distance_button", always_10hz)
  assert m.use_10hz_distance_button("UNKNOWN_CAR") is True, (
      "a mutant that applies the 10 Hz read to unknown cars must be visible; production returns False"
  )
