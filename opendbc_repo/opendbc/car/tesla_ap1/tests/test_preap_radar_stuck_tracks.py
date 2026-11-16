"""Pre-AP stuck radar track filter (docs/tesla/DIVERGENCES_preap_radar_filters.md (2))."""
from opendbc.car.tesla_ap1.preap_radar_filters import STUCK_WINDOW_S, StuckTrackFilter

DT = 0.05


def run(f, d_of_t, v_rel, v_ego_of_t, seconds, tid=0):
  out = []
  for k in range(int(round(seconds / DT)) + 1):
    t = k * DT
    out.append((t, f.update(tid, d_of_t(t), v_rel, v_ego_of_t(t), t)))
  return out


def test_fixed_range_while_ego_accelerates_is_flagged_after_the_window():
  out = run(StuckTrackFilter(), lambda t: 17.25, 0.0, lambda t: 1.0 * t, 8.0)   # ego 0 -> 8 m/s, range fixed (measured phantom)
  first = next(t for t, f in out if f)
  assert STUCK_WINDOW_S * 0.95 <= first <= STUCK_WINDOW_S + 0.1
  assert all(f for t, f in out if t >= first)


def test_lsb_noise_on_the_range_still_flags():
  out = run(StuckTrackFilter(), lambda t: 16.4375 + (0.0625 if int(t / DT) % 3 == 0 else 0.0), 0.0625, lambda t: 1.0 * t, 8.0)
  assert out[-1][1]


def test_real_lead_at_matched_speed_without_ego_speed_change_is_kept():
  assert not any(f for _, f in run(StuckTrackFilter(), lambda t: 30.0, 0.0, lambda t: 20.0, 20.0))


def test_real_lead_closing_or_opening_is_kept():
  assert not any(f for _, f in run(StuckTrackFilter(), lambda t: 40.0 - 0.5 * t, -0.5, lambda t: 10.0 + 0.8 * t, 20.0))
  assert not any(f for _, f in run(StuckTrackFilter(), lambda t: 30.0, 0.3, lambda t: 10.0 + 0.8 * t, 20.0))


def test_flagged_track_released_when_range_moves_and_pruned_when_gone():
  f = StuckTrackFilter()
  out = run(f, lambda t: 17.0, 0.0, lambda t: t, 8.0)
  assert out[-1][1]
  assert not f.update(0, 18.0, 0.0, 9.0, 8.05)          # range moved 1 m inside the window: released
  run(f, lambda t: 17.0, 0.0, lambda t: t, 8.0, tid=5)
  f.prune({0})
  assert 5 not in f.hist and 5 not in f.flagged
