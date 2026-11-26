"""Pre-rename logs and tools: service names, wire compatibility and the legacy-name lookup."""
from pathlib import Path

import pytest

from openpilot.cereal import log, custom
from openpilot.cereal.services import LEGACY_SERVICE_ALIASES, SERVICE_LIST, canonical_service_name
from openpilot.tools.lib.logreader import LogReader

FIXTURE = Path(__file__).parent / "fixtures" / "pre_rename_bogpilot.rlog.zst"

# Event union ordinals fixed by the 0.9.7-era schema; they, not the names, are what is on the wire.
ORDINALS = {
  "bogpilotCarControl": 107, "bogpilotCarParams": 108, "bogpilotCarState": 109, "bogpilotControlsState": 110,
  "bogpilotDeviceState": 111, "bogpilotModelV2": 112, "bogpilotNavigation": 113, "bogpilotOnroadEvents": 114,
  "bogpilotPlan": 115, "bogpilotRadarState": 116,
}


def test_aliases_point_at_real_services():
  assert len(LEGACY_SERVICE_ALIASES) == len(ORDINALS)
  for old, new in LEGACY_SERVICE_ALIASES.items():
    assert old.startswith("frogpilot") and new in SERVICE_LIST and old not in SERVICE_LIST
    assert canonical_service_name(old) == new
  assert canonical_service_name("carState") == "carState"


def test_union_ordinals_unchanged():
  fields = {name: f.proto.ordinal.explicit for name, f in log.Event.schema.fields.items() if name in ORDINALS}
  assert fields == ORDINALS
  ev = log.Event.new_message()
  for name in ORDINALS:
    ev.init(name) if name != "bogpilotOnroadEvents" else ev.init(name, 1)
    assert ev.which() == name


def test_old_names_are_gone_from_schema():
  assert not any(f.startswith("frogpilot") for f in log.Event.schema.fields)
  assert not any(n.startswith("FrogPilot") for n in dir(custom))


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_pre_rename_rlog_still_decodes():
  """FIXTURE was recorded with the pre-rename schema (frogpilotPlan / frogpilotCarState / frogpilotRadarState...)."""
  lr = list(LogReader(str(FIXTURE)))
  assert lr
  kinds = {m.which() for m in lr}
  assert {"bogpilotPlan", "bogpilotCarState", "bogpilotRadarState"} <= kinds
  plan = next(m for m in lr if m.which() == "bogpilotPlan")
  assert plan.bogpilotPlan.vCruise == pytest.approx(31.25)
  assert plan.bogpilotPlan.slcSpeedLimit == pytest.approx(22.5)
  # the old name still finds the same events
  assert len(list(LogReader(str(FIXTURE)).filter("frogpilotPlan"))) == len(list(LogReader(str(FIXTURE)).filter("bogpilotPlan")))
  assert next(iter(LogReader(str(FIXTURE)).filter("frogpilotCarState"))).accelPressed is True
