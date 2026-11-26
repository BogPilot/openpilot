"""Dead-torque rpm gate per car: 5500 rpm on the AP1 Model X (its rear unit turns slower per mph), 6000 on the AP1 Model S and
Pre-AP (unchanged); release 5000 on all. Single-motor gauge mode only (no fresh 0x186)."""
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

DT = 0.05
ON = PED.PedalPolicy(show=True)


def run(fp, rpm, seconds=1.0):
  g, t, out = PED.PedalGauge(), 0.0, None
  for _ in range(int(seconds / DT)):
    t += DT
    out = g.update(ON, True, t, "ap1", brake_pressed=False, brake_level=0.0, pedal_pos=0.0, op_accel=-1.0, long_active=True,
                   motor_torque_nm=0.0, motor_rpm=rpm, fingerprint=fp)
  return g, out


def test_gate_values():
  assert PED.dead_rpm_on("TESLA_AP1_MODELX") == 5500.0
  assert PED.dead_rpm_on("TESLA_AP1_MODELS") == PED.dead_rpm_on("TESLA_PREAP_MODELS") == PED.dead_rpm_on(None) == 6000.0
  assert PED.TORQUE_DEAD_RPM_OFF == 5000.0
  assert PED.TorqueTrust().rpm_on == 6000.0


def test_x_dead_at_5700_s_and_preap_not():
  assert run("TESLA_AP1_MODELX", 5700.0)[0].trust.dead is True
  assert run("TESLA_AP1_MODELS", 5700.0)[0].trust.dead is False
  assert run("TESLA_PREAP_MODELS", 5700.0)[0].trust.dead is False
  assert run("TESLA_AP1_MODELS", 6100.0)[0].trust.dead is True


def test_x_below_5500_never_dead():
  assert run("TESLA_AP1_MODELX", 5400.0, 5.0)[0].trust.dead is False
