"""card's 10 Hz params thread saves the trim detection (TeslaTrimDetected) only when something new is known."""
from types import SimpleNamespace

from opendbc.car.tesla_ap1 import trims as T
from openpilot.selfdrive.car.tesla_trim_persist import TrimPersist, detection_from_car_state

X_FP, S_FP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS"


def cs(layout, perf=0, rear=250.0, front=244.0, measured=True):
  return SimpleNamespace(bogpilot=SimpleNamespace(ap1DriveLayout=layout, ap1PerfRear=perf, ap1RearRpmPerMs=rear,
                                                  ap1FrontRpmPerMs=front, ap1RpmPerMsMeasured=measured))


def test_unknown_layout_never_writes(tmp_path):
  p = TrimPersist(S_FP, tmp_path / "d")
  assert detection_from_car_state(cs(0), S_FP) is None
  assert p.poll(cs(0), 0.0) is False and not (tmp_path / "d").exists()


def test_writes_once_then_only_on_change(tmp_path):
  path = tmp_path / "d"
  p = TrimPersist(X_FP, path)
  assert p.poll(cs(2, 2), 0.0) is True
  assert T.read_detected(path=path) == T.Detected("X", 2, 2, 250.0, 244.0)
  assert p.poll(cs(2, 2), 0.5) is False                        # rate limited
  assert p.poll(cs(2, 2, rear=250.5), 2.0) is False            # 0.2 % move: no write
  assert p.poll(cs(2, 2, rear=252.0), 3.0) is True and p.writes == 2


def test_unmeasured_drive_keeps_what_an_earlier_drive_learned(tmp_path):
  path = tmp_path / "d"
  T.write_detected(T.Detected("X", 2, 2, 250.0, 244.0), path)
  p = TrimPersist(X_FP, path)
  assert p.poll(cs(2, 0, measured=False), 0.0) is False         # nothing new: perf and k kept
  assert T.read_detected(path=path) == T.Detected("X", 2, 2, 250.0, 244.0)


def test_other_cars_ignored(tmp_path):
  p = TrimPersist("TESLA_MODEL_Y", tmp_path / "d")
  assert p.poll(cs(2, 2), 0.0) is False and not (tmp_path / "d").exists()
  assert TrimPersist(S_FP, tmp_path / "d").poll(None, 0.0) is False


def test_single_motor_has_no_front(tmp_path):
  path = tmp_path / "d"
  assert TrimPersist(S_FP, path).poll(cs(1, 0, rear=265.0, front=float("nan")), 0.0) is True
  assert T.read_detected(path=path) == T.Detected("S", 1, 0, 265.0, None)
