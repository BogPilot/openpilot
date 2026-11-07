"""Real SelfdriveD alert-method subprocess proof; no vehicle or control output."""
from pathlib import Path
from types import SimpleNamespace as NS
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from openpilot.selfdrive.ui.bogpilot import phase2_alerts as optional


def daemon_fixture():
  from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD, LONGITUDINAL_PERSONALITY_MAP
  from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
  from openpilot.selfdrive.selfdrived.events import ET
  from opendbc.car import structs as car
  d = SelfdriveD.__new__(SelfdriveD)
  d.enabled = False
  d.personality = next(iter(LONGITUDINAL_PERSONALITY_MAP))
  d.state_machine = NS(current_alert_types=[ET.PERMANENT], soft_disable_timer=0)
  d.CP = car.CarParams.new_message()
  d.is_metric = True
  d.sm = NS(frame=0, all_checks=lambda _: True, recv_time=dict.fromkeys(("modelV2", "radarState"), time.monotonic()))
  stock = optional.make_alert("GreenLightAlert")
  stock.alert_type = "stockSentinel/permanent"
  stock.alert_text_1 = "STOCK SAFETY SENTINEL"
  stock.priority = 99
  d.events = NS(create_alerts=lambda *_: [stock])
  d.AM = AlertManager()
  d.bogpilot_alerts = NS(store=NS(get_bool=lambda *_, **__: True), update=lambda *_: ())
  cs = car.CarState.new_message(canValid=True, standstill=True, gearShifter="drive")
  return d, cs


def raise_optional(*_):
  raise RuntimeError("optional producer fault")


def child_process_proof():
  d, cs = daemon_fixture()
  calls = []
  def broken(*_):
    calls.append(1)
    raise_optional()
  d.bogpilot_alerts.update = broken
  for frame in range(20):
    d.sm.frame = frame
    d.update_alerts(cs)
    assert d.bogpilot_alerts is None
    assert "stockSentinel/permanent" in d.AM.alerts
    assert d.AM.alerts["stockSentinel/permanent"].alert.alert_text_1 == "STOCK SAFETY SENTINEL"
  assert calls == [1]
  print("PRODUCTION_SELFD_METHOD_SUBPROCESS_PASS_20_FRAMES_OPTIONAL_DISABLED_STOCK_RETAINED")


class TestOptionalFailureBoundary(unittest.TestCase):
  def test_constructor_fault_is_optional_only(self):
    with patch.object(optional, "Phase2AlertRuntime", side_effect=OSError("optional store unavailable")):
      self.assertIsNone(optional.create_optional_alert_runtime())

  def test_producer_and_preference_faults_disable_until_restart(self):
    for field in ("producer", "preferences", "eligibility"):
      with self.subTest(field=field):
        d, cs = daemon_fixture()
        if field == "producer":
          d.bogpilot_alerts.update = raise_optional
        elif field == "preferences":
          d.bogpilot_alerts.store.get_bool = raise_optional
        else:
          d.sm.all_checks = raise_optional
        d.update_alerts(cs)
        self.assertIsNone(d.bogpilot_alerts)
        self.assertIn("stockSentinel/permanent", d.AM.alerts)

  def test_partial_optional_dispatch_is_removed_not_stock(self):
    d, cs = daemon_fixture()
    def broken(am, frame, *_):
      am.add_many(frame, [optional.make_alert("GreenLightAlert")])
      raise_optional()
    with patch.object(optional, "add_to_alert_manager", side_effect=broken):
      d.update_alerts(cs)
    self.assertIsNone(d.bogpilot_alerts)
    self.assertIn("stockSentinel/permanent", d.AM.alerts)
    self.assertNotIn("bogpilotGreenLightAlert/permanent", d.AM.alerts)

  def test_stock_create_add_and_process_exceptions_are_not_caught(self):
    for field in ("create_alerts", "add_many", "process_alerts"):
      with self.subTest(field=field):
        d, cs = daemon_fixture()
        target = d.events if field == "create_alerts" else d.AM
        with patch.object(target, field, side_effect=RuntimeError("critical stock fault")):
          with self.assertRaisesRegex(RuntimeError, "critical stock fault"):
            d.update_alerts(cs)

  def test_shutdown_is_not_swallowed(self):
    d, cs = daemon_fixture()
    with patch.object(d.bogpilot_alerts, "update", side_effect=KeyboardInterrupt):
      with self.assertRaises(KeyboardInterrupt):
        d.update_alerts(cs)

  def test_actual_production_method_in_fresh_native_process(self):
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25)
    self.assertEqual(p.returncode, 0, p.stdout)
    self.assertIn("PRODUCTION_SELFD_METHOD_SUBPROCESS_PASS_20_FRAMES", p.stdout)

  def test_aol_core_and_callers_absent(self):
    root = Path(__file__).resolve().parents[4]
    self.assertFalse((root / "opendbc_repo/opendbc/car/tesla_ap1/aol_gate.py").exists())
    for name in ("openpilot/selfdrive/car/ap1_runtime.py", "openpilot/selfdrive/car/card.py", "openpilot/selfdrive/controls/controlsd.py"):
      source = (root / name).read_text()
      for token in ("AP1AolGate", "Ap1Lateral", "aol_active", "aol_bit", "apply_ap1_alternative_experience"):
        self.assertNotIn(token, source)
    self.assertIn("CC.latActive = self.sm['selfdriveState'].active and", (root / "openpilot/selfdrive/controls/controlsd.py").read_text())


if __name__ == "__main__":
  if sys.argv[1:] == ["--child"]:
    child_process_proof()
  else:
    unittest.main()
