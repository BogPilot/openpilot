"""A Pre-AP radar that stops after speaking is advisory, as NAP (opendbc/car/tesla/radar_interface.py:176-177 @ opendbc 508d26fcb:
no trigger message, nothing published, no error): its tracks are dropped (camera leads), the radar reads not VALID (card raises the
one "Radar not ready" warning) and no error is set. A radar parser that goes invalid while frames still arrive stays canError, as
NAP :190-191."""
from opendbc.car.tesla_ap1.radar_interface import PREAP_MISSING_RADAR_FRAMES, PREAP_MISSING_RADAR_PUBLISH_DIV
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, long_paths  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_radar_advisory import DT, no_errors, radar_frames, ri_on, run

SGU_ADDR = 0x301


def silence(ri, n):
  return [o for o in (ri.update([]) for _ in range(n)) if o is not None]


def test_before_the_first_message_unchanged(long_paths):
  ri = ri_on(long_paths)
  outs = silence(ri, PREAP_MISSING_RADAR_FRAMES * 4)
  assert len(outs) == PREAP_MISSING_RADAR_FRAMES * 4 // PREAP_MISSING_RADAR_PUBLISH_DIV and no_errors(outs)
  assert not any(o.points for o in outs) and not ri.preap_radar_spoke and not ri.preap_radar_valid


def test_silence_after_the_first_message_is_advisory(long_paths):
  ri = ri_on(long_paths)
  run(ri, 1.0, 6.0)
  assert ri.preap_radar_valid and ri.pts
  early = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES - 1)]
  assert all(o is None for o in early)                                # under 0.5 s: nothing new, as before
  outs = silence(ri, PREAP_MISSING_RADAR_FRAMES * 6)                   # 3 s more of silence
  assert outs and no_errors(outs)                                      # no canError, radarFault or radarUnavailableTemporary
  assert not any(o.points for o in outs) and not ri.pts                # points dropped: camera leads
  assert not ri.preap_radar_valid                                      # card raises the one warning


def test_frames_returning_recover(long_paths):
  ri = ri_on(long_paths)
  run(ri, 1.0, 6.0)
  silence(ri, PREAP_MISSING_RADAR_FRAMES * 2)
  assert not ri.preap_radar_valid
  outs = run(ri, 6.0, 12.0)
  assert no_errors(outs) and ri.frames_without_radar == 0
  assert ri.preap_radar_valid and len(outs[-1].points) == 1


def test_invalid_parser_while_frames_arrive_is_canerror(long_paths):
  ri = ri_on(long_paths)
  run(ri, 1.0, 4.0)
  outs, t = [], 4.0
  while t < 7.0:                                                      # the trigger keeps coming, 0x301 stops: parser invalid
    [(ns, msgs)] = radar_frames(t)
    outs.append(ri.update([(ns, [m for m in msgs if m[0] != SGU_ADDR])]))
    t += DT
  outs = [o for o in outs if o is not None]
  assert outs and outs[-1].errors.canError
  assert sum(o.errors.canError for o in outs) >= len(outs) // 2
