"""Synthetic managerState samples only; no device, process or log access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("manager_smoke", Path(__file__).parents[1] / "manager_smoke.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample(t, ui=6663, lm=6662, offroad=True, valid=True, extra=()):
  procs = [dict(name="ui", pid=ui, running=ui > 0, shouldBeRunning=True, exitCode=0),
           dict(name="logmessaged", pid=lm, running=lm > 0, shouldBeRunning=True, exitCode=0),
           dict(name="hardwared", pid=0, running=False, shouldBeRunning=False, exitCode=0)]
  procs += [dict(name=n, pid=99, running=True, shouldBeRunning=True, exitCode=0) for n in extra]
  return dict(t=t, managerState_valid=valid, offroad=offroad, processes=procs)


class SmokeTests(unittest.TestCase):
  def test_stable_quiet_startup_passes(self):
    # Quiet logs are irrelevant: verdict uses only process state.
    self.assertEqual(m.evaluate([sample(t) for t in range(0, 62, 2)])[0], "PASS")

  def test_restart_detected(self):
    v, r = m.evaluate([sample(0), sample(30, ui=7000), sample(61, ui=7000)])
    self.assertEqual(v, "FAIL"); self.assertIn("restarted", r[0])

  def test_short_window_insufficient_not_fail(self):
    self.assertEqual(m.evaluate([sample(0), sample(30)])[0], "INSUFFICIENT")

  def test_not_running_offroad_invalid(self):
    self.assertEqual(m.evaluate([sample(0), sample(61, ui=0)])[0], "FAIL")
    self.assertEqual(m.evaluate([sample(0), sample(61, offroad=False)])[0], "FAIL")
    self.assertEqual(m.evaluate([sample(0), sample(61, valid=False)])[0], "FAIL")

  def test_crash_exit_code(self):
    s = sample(61); s["processes"][0]["exitCode"] = -11
    self.assertEqual(m.evaluate([sample(0), s])[0], "FAIL")

  def test_forbidden_process(self):
    self.assertEqual(m.evaluate([sample(0), sample(61, extra=("pandad",))], forbidden=("pandad",))[0], "FAIL")

  def test_bad_times(self):
    self.assertEqual(m.evaluate([sample(5), sample(0)])[0], "INSUFFICIENT")
    self.assertEqual(m.evaluate([sample(0)])[0], "INSUFFICIENT")

  def test_cli_exit_codes(self):
    with tempfile.TemporaryDirectory() as d:
      p = Path(d, "s.json")
      p.write_text(json.dumps([sample(0), sample(61)]))
      self.assertEqual(m.main([str(p), "--forbid", "hardwared,pandad"]), 0)
      p.write_text(json.dumps([sample(0), sample(10)]))
      self.assertEqual(m.main([str(p)]), 2)


class PackagedCollectorNamespaceTests(unittest.TestCase):
  def test_collector_uses_actual_packaged_cereal_namespace(self):
    import ast
    import inspect
    import textwrap
    imports = [a.name for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(m.collect))))
               if isinstance(n, ast.Import) for a in n.names]
    self.assertIn("openpilot.cereal.messaging", imports)
    self.assertNotIn("cereal.messaging", imports)


if __name__ == "__main__":
  unittest.main()
