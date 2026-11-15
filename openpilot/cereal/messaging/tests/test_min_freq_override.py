"""SubMaster min_freq is a lower-only per-service FrequencyTracker override."""
import pytest

from openpilot.cereal import messaging
from openpilot.cereal.services import SERVICE_LIST


def radar_sm(**kwargs):
  return messaging.SubMaster(['modelV2', 'carState', 'radarTracks'], poll='modelV2', **kwargs)


def test_default_radartracks_floor_is_stock_8_and_max_24():
  sm = radar_sm()
  assert sm.freq_tracker['radarTracks'].min_freq == 8.0
  assert sm.freq_tracker['radarTracks'].max_freq == 24.0
  assert (10. / SERVICE_LIST['radarTracks'].frequency) == 0.5


def test_lower_only_override_sets_radartracks_min_and_leaves_max():
  stock = radar_sm()
  sm = radar_sm(min_freq={'radarTracks': 5.0})
  assert sm.freq_tracker['radarTracks'].min_freq == 5.0
  assert sm.freq_tracker['radarTracks'].max_freq == 24.0
  # Polled and other non-overridden services keep their computed floors.
  assert sm.freq_tracker['modelV2'].min_freq == stock.freq_tracker['modelV2'].min_freq == 16.0
  assert sm.freq_tracker['carState'].min_freq == stock.freq_tracker['carState'].min_freq
  assert sm.freq_tracker['carState'].max_freq == stock.freq_tracker['carState'].max_freq
  assert (10. / SERVICE_LIST['radarTracks'].frequency) == 0.5


def test_override_rejects_a_higher_floor():
  with pytest.raises(AssertionError, match="lower-only"):
    radar_sm(min_freq={'radarTracks': 9.0})


def test_override_must_be_positive():
  with pytest.raises(AssertionError, match="must be > 0"):
    radar_sm(min_freq={'radarTracks': 0.0})
  with pytest.raises(AssertionError, match="must be > 0"):
    radar_sm(min_freq={'radarTracks': -1.0})


@pytest.mark.parametrize("ignore_kw", ["ignore_avg_freq", "ignore_alive", "ignore_valid"])
def test_override_rejects_ignore_lists(ignore_kw):
  with pytest.raises(AssertionError, match="ignore list"):
    radar_sm(min_freq={'radarTracks': 5.0}, **{ignore_kw: ['radarTracks']})


def test_override_rejects_unknown_service():
  with pytest.raises(AssertionError, match="unknown service"):
    radar_sm(min_freq={'carControl': 5.0})
