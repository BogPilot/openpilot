"""AP1 lead side check (phantom brake Option C) setting and geometry (tesla_ap1/lead_side_check.py)."""
import pytest

from opendbc.car.tesla_ap1 import lead_side_check as lsc


def test_constants():
  assert lsc.SIDE_CHECK_KEY == "AP1LeadSideCheck"
  assert lsc.SIDE_CHECK_LIMIT_M == 2.5 and lsc.SIDE_CHECK_YSTD_FACTOR == 2.0
  assert abs(lsc.SIDE_CHECK_MIN_SPEED_MS - 15.2) < 0.01          # 34 mph
  assert lsc.SIDE_CHECK_MIN_SPEED_MS * 2.23694 >= 34.0 - 1e-6     # never active below 34 mph


@pytest.mark.parametrize("stored,expected", [(None, False), ("", False), ("1", True), ("true", True), ("on", True), (" ON\n", True),
                                             ("0", False), ("off", False), ("false", False), ("junk", False), (b"1", True)])
def test_default_off_and_parsing(tmp_path, stored, expected):
  if stored is None:
    assert lsc.side_check_enabled(path=tmp_path / "missing") is False
  else:
    assert lsc.side_check_enabled(stored=stored) is expected


def test_write_round_trip(tmp_path):
  p = tmp_path / "d" / lsc.SIDE_CHECK_KEY
  lsc.set_side_check(True, path=p)
  assert p.read_text() == "1" and lsc.side_check_enabled(path=p)
  lsc.set_side_check(False, path=p)
  assert p.read_text() == "0" and not lsc.side_check_enabled(path=p)


@pytest.mark.parametrize("fp,op_long,expected", [("TESLA_AP1_MODELS", False, True), ("TESLA_AP1_MODELS", True, True),
                                                 ("TESLA_AP1_MODELX", True, True), ("TESLA_AP1_MODELX", False, False),
                                                 ("TESLA_PREAP_MODELS", True, False), ("TESLA_MODEL_3", True, False), ("", True, False)])
def test_platform(fp, op_long, expected):
  assert lsc.side_check_platform(fp, op_long) is expected
  assert lsc.side_check_active(fp, op_long, stored="1") is expected
  assert lsc.side_check_active(fp, op_long, stored="0") is False


def test_limit_and_sign():
  assert lsc.side_check_limit(0.5) == 2.5 and lsc.side_check_limit(1.5) == 3.0
  # radar yRel is left-positive, the model's y is right-positive: same car => yRel == -y
  assert lsc.track_within_side_limit(1.0, -1.0, 0.5)
  assert lsc.track_within_side_limit(3.5, -1.0, 0.5)              # 2.5 m apart: kept (limit is inclusive)
  assert not lsc.track_within_side_limit(3.6, -1.0, 0.5)
  assert lsc.track_within_side_limit(3.6, -1.0, 1.5)              # wide camera uncertainty widens the limit
