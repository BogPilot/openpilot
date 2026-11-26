"""Pre-AP userspace pedal guard: a pedal ENABLE frame goes out only while the pull FSM is in FULL (second pull of a
NAP-style double pull, NAP preap/engagement.py:131 @ e99f4dc75). Anything else is sent as the enable=0 passthrough frame."""
from types import SimpleNamespace

from opendbc.car import structs
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.long_controller import PreAPLongController
from opendbc.car.tesla_ap1.preap.pedal_can import PedalCommandCounter
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _act, _params_dir, _pedal_frame, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_pedal_authority import _ready


def _send(mode, enable=1, cmd=0.4):
  lc = PreAPLongController(PedalCommandCounter(), lambda: 2)
  quiet = dict(real_brake_pressed=False, out=SimpleNamespace(gasPressed=False), preap_panda_gas_pressed=False, preap_gas_clear_updates=5,
               preap_standstill_hold=False)
  cs = SimpleNamespace(**quiet) if mode is None else SimpleNamespace(preap_fsm_mode=mode, **quiet)
  sends = []
  lc._append_pedal_command(sends, cs, cmd, enable)
  return sends[0].dat, getattr(cs, "preap_pedal_guard_blocks", 0)


def test_enable_only_in_full():
  dat, blocks = _send(int(Mode.FULL))
  assert dat[4] & 0x80 and blocks == 0


def test_steering_only_modes_send_the_passthrough_frame():
  for mode in (Mode.OFF, Mode.LOCKOUT, Mode.LAT_PENDING, Mode.LAT_ONLY):
    dat, blocks = _send(int(mode))
    assert not dat[4] & 0x80 and blocks == 1, mode
    assert dat[:4] == _send(int(Mode.FULL), enable=0, cmd=0.0)[0][:4]   # same bytes as the disabled path


def test_missing_or_invalid_mode_is_blocked():
  for mode in (None, 99, "x"):
    dat, blocks = _send(mode)
    assert not dat[4] & 0x80 and blocks == 1, mode


def test_disabled_frames_are_never_counted():
  _, blocks = _send(int(Mode.LAT_ONLY), enable=0, cmd=0.0)
  assert blocks == 0


def _run(rig, ctl, frames, pulls, long_active_always=True, hook=None):
  enabled, outs, op = 0, [], False
  for n in range(frames):
    if hook:
      hook(n, rig)
    _pedal_frame(rig, n // 2)
    out = rig.frame(stalk=PULL if n in pulls else 0, op=op)
    rig.cs.out = out
    req = rig.cs.update_button_enable(out.buttonEvents)
    op = bool(op and out.cruiseState.enabled) or bool(req and out.cruiseState.available)
    # longActive asked for even on steering only: the guard (not openpilot) must keep the pedal off
    cc = structs.CarControl.new_message(enabled=op, latActive=op, longActive=op if long_active_always else (op and not out.bogpilot.preapLatOnly),
                                        actuators=_act(0.3)).as_reader()
    _, sends = ctl.update(cc, rig.cs, rig.nanos)
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      if addr == 0x551 and dat[4] & 0x80:
        enabled += 1
    outs.append((op, out))
  return enabled, outs


def test_single_pull_never_enables_the_pedal_even_if_long_is_asked():
  rig, ctl = _ready()
  enabled, outs = _run(rig, ctl, 400, pulls={20})
  assert outs[-1][0] and outs[-1][1].bogpilot.preapLatOnly
  assert enabled == 0


def test_double_pull_enables_the_pedal():
  rig, ctl = _ready()
  enabled, outs = _run(rig, ctl, 400, pulls={20, 45}, long_active_always=False)
  assert outs[-1][0] and not outs[-1][1].bogpilot.preapLatOnly
  assert enabled > 20


def test_panda_tx_block_in_full_drops_to_steering_only():
  rig, ctl = _ready()

  def hook(n, r):
    if n == 300:
      r.cs.preap_panda_tx_blocked = 1
  enabled, outs = _run(rig, ctl, 420, pulls={20, 45}, long_active_always=False, hook=hook)
  assert not outs[299][1].bogpilot.preapLatOnly
  op, out = outs[-1]
  assert op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked
  assert rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)

# INTERCEPTOR_GAS above the panda press threshold (tesla_preap.h:135, raw 650 ≈ 10.16 in DBC units).
_GAS_ABOVE = 20.0
_GAS_BELOW = 0.8


def _run_press(rig, ctl, frames, pulls, *, gas_frames=(), block_frames=(), guard_at=None, block_count=1):
  """Replay-style 10 ms steps. gas_frames send INTERCEPTOR_GAS above the panda threshold; block_frames inject a
  panda TX-block delta. Returns (enable-bits, outs) where each out is (op, CarState, enable_bit)."""
  bits, outs, op = [], [], False
  for n in range(frames):
    raw = _GAS_ABOVE if n in gas_frames else _GAS_BELOW
    _pedal_frame(rig, n // 2, raw=raw)
    if n in block_frames:
      rig.cs.preap_panda_tx_blocked = block_count
    if guard_at is not None and n == guard_at:
      rig.cs.preap_pedal_guard_blocks = int(getattr(rig.cs, "preap_pedal_guard_blocks", 0)) + 1
    out = rig.frame(stalk=PULL if n in pulls else 0, op=op)
    rig.cs.out = out
    req = rig.cs.update_button_enable(out.buttonEvents)
    op = bool(op and out.cruiseState.enabled) or bool(req and out.cruiseState.available)
    cc = structs.CarControl.new_message(enabled=op, latActive=op, longActive=op and not out.bogpilot.preapLatOnly,
                                        actuators=_act(0.3)).as_reader()
    _, sends = ctl.update(cc, rig.cs, rig.nanos)
    enable_bit = 0
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      if addr == 0x551 and dat[4] & 0x80:
        enable_bit = 1
    bits.append(enable_bit)
    outs.append((op, out, enable_bit))
  return bits, outs


def test_gas_press_tx_block_keeps_full_and_enable_resumes_after_release():
  """FULL + gas press: a TX block on the first pressed frame must not demote. No ENABLE=1 while pressed;
  ENABLE=1 resumes one update after release."""
  rig, ctl = _ready()
  press = 300
  hold = range(press, press + 10)          # 100 ms of gas
  bits, outs = _run_press(rig, ctl, 360, pulls={20, 45}, gas_frames=set(hold), block_frames={press})
  assert not outs[press - 1][1].bogpilot.preapLatOnly
  # through the press and the block, speed control stays on
  for n in range(press, press + 10):
    op, out, bit = outs[n]
    assert op and not out.bogpilot.preapLatOnly and rig.cs.preap_fsm_mode == int(Mode.FULL)
    assert not rig.cs.decision.speed_blocked
    assert bit == 0, n                     # no ENABLE=1 while pressed
  # release frame: still held for the one clear update (preap_gas_clear_updates < 2)
  assert outs[press + 10][2] == 0
  # Pedal commands are 50 Hz (every other 10 ms frame). ENABLE=1 resumes on the next
  # command slot after that clear update, not on the off-cycle frame.
  assert outs[press + 11][2] == 0
  assert outs[press + 12][2] == 1
  assert outs[press + 12][0] and not outs[press + 12][1].bogpilot.preapLatOnly
  assert not rig.cs.decision.speed_blocked


def test_tx_block_with_no_press_still_demotes():
  rig, ctl = _ready()
  bits, outs = _run_press(rig, ctl, 420, pulls={20, 45}, block_frames={300})
  assert not outs[299][1].bogpilot.preapLatOnly
  op, out, _ = outs[-1]
  assert op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked
  assert rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


def test_tx_block_400ms_after_press_still_demotes():
  rig, ctl = _ready()
  press = 300
  # 10 ms/frame: 400 ms after the press edge is frame 340, with the pedal already released
  bits, outs = _run_press(rig, ctl, 400, pulls={20, 45},
                          gas_frames=set(range(press, press + 5)), block_frames={press + 40})
  assert not outs[press + 20][1].bogpilot.preapLatOnly
  op, out, _ = outs[-1]
  assert op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked
  assert rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


def test_guard_block_during_press_window_still_demotes():
  """Only TX-block deltas explained by the press are ignored; a userspace guard block still demotes."""
  rig, ctl = _ready()
  press = 300
  bits, outs = _run_press(rig, ctl, 360, pulls={20, 45},
                          gas_frames=set(range(press, press + 10)), guard_at=press)
  op, out, _ = outs[-1]
  assert op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked
  assert rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


# safetyTxBlocked is one running total for every address (panda can_common.h safety_tx_blocked, health
# safety_tx_blocked_pkt, cereal PandaState.safetyTxBlocked), so a block cannot be attributed to 0x551. The press window
# therefore ignores any TX-block delta (all addresses); blocks outside it still demote (tests above).
def test_tx_block_input_is_one_total_without_an_address():
  import pathlib
  import re
  root = pathlib.Path(__file__).resolve().parents[5]
  capnp = root / "openpilot" / "cereal" / "log.capnp"
  if not capnp.exists():
    import pytest
    pytest.skip("cereal schema not in this checkout")
  text = capnp.read_text()
  body = text[re.search(r"^struct PandaState\b", text, re.M).start():]
  body = body[:body.index("\n}\n")]
  blocked = re.findall(r"^\s*(\w*[Bb]locked\w*) @\d+ :(\w+);", body, re.M)
  assert blocked == [("safetyTxBlocked", "UInt32")]


def test_multi_address_tx_block_total_inside_the_press_window_keeps_full():
  rig, ctl = _ready()
  press = 300
  bits, outs = _run_press(rig, ctl, 330, pulls={20, 45}, gas_frames=set(range(press, press + 10)),
                          block_frames={press + 5}, block_count=7)
  op, out, _ = outs[-1]
  assert op and not out.bogpilot.preapLatOnly and not rig.cs.decision.speed_blocked
  assert rig.cs.preap_fsm_mode == int(Mode.FULL)
