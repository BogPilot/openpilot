"""Sidebar IP address (ShowIP): reader, gate wiring and drawing (headless)."""
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.bogpilot import sidebar_metrics as SM


class TestReader(unittest.TestCase):
  def test_unknown_interface_reads_empty(self):
    self.assertEqual(SM.wifi_ipv4("nosuch0"), "")

  def test_reader_caches_for_five_seconds(self):
    now, calls = [0.0], []
    r = SM.IpReader(read=lambda: calls.append(1) or "192.168.1.20", clock=lambda: now[0])
    for _ in range(5):
      self.assertEqual(r.get(), "192.168.1.20")
    self.assertEqual(len(calls), 1)
    now[0] = 5.5
    r.get()
    self.assertEqual(len(calls), 2)

  def test_reader_failure_is_empty(self):
    def boom():
      raise RuntimeError("no")
    self.assertEqual(SM.IpReader(read=boom).get(), "")
    self.assertEqual(SM.IpReader(read=lambda: None).get(), "")

  def test_reader_sends_nothing(self):
    import inspect
    src = inspect.getsource(SM.wifi_ipv4)
    for needle in ("connect(", "sendto", "send(", "urlopen", "requests"):
      self.assertNotIn(needle, src)


class Gate:
  def __init__(self, on):
    self.on = on

  def get(self):
    return self.on


def make_sidebar(m, on, ip="192.168.1.20"):
  s = m.Sidebar.__new__(m.Sidebar)
  s._ip_gate = Gate(on)
  s._ip_reader = SimpleNamespace(get=lambda: ip)
  s._ip_text = ""
  s._net_type, s._net_strength = "Wi-Fi", 3
  s._font_regular = object()
  return s


class TestSidebar(unittest.TestCase):
  def setUp(self):
    from openpilot.selfdrive.ui.layouts import sidebar as m
    self.m = m
    self.calls = []
    self._saved = (m.rl.draw_circle, m.rl.draw_text_ex, m.measure_text_cached)
    m.rl.draw_circle = lambda *a: self.calls.append(("dot",))
    m.rl.draw_text_ex = lambda font, text, pos, size, spacing, color: self.calls.append(("text", text, pos.x, pos.y, size))
    m.measure_text_cached = lambda font, text, size: SimpleNamespace(x=len(text) * size * 0.55, y=size * 1.2)
    self.addCleanup(lambda: (setattr(m.rl, "draw_circle", self._saved[0]), setattr(m.rl, "draw_text_ex", self._saved[1]),
                             setattr(m, "measure_text_cached", self._saved[2])))

  def test_off_keeps_the_signal_dots(self):
    s = make_sidebar(self.m, False)
    s._update_ip()
    self.assertEqual(s._ip_text, "")
    s._draw_network_indicator(self.m.rl.Rectangle(0, 0, 300, 1080))
    self.assertEqual(sum(c == ("dot",) for c in self.calls), 5)
    self.assertEqual([c[1] for c in self.calls if c[0] == "text"], ["Wi-Fi"])

  def test_on_replaces_the_dots_with_the_address_and_keeps_the_type(self):
    s = make_sidebar(self.m, True)
    s._update_ip()
    self.assertEqual(s._ip_text, "192.168.1.20")
    s._draw_network_indicator(self.m.rl.Rectangle(0, 0, 300, 1080))
    self.assertNotIn(("dot",), self.calls)
    texts = [c for c in self.calls if c[0] == "text"]
    self.assertEqual([t[1] for t in texts], ["192.168.1.20", "Wi-Fi"])
    self.assertEqual((texts[0][2], texts[0][4]), (50, 30))

  def test_no_address_shows_dashes(self):
    s = make_sidebar(self.m, True, ip="")
    s._update_ip()
    self.assertEqual(s._ip_text, "--")

  def test_long_address_shrinks_to_fit_the_sidebar(self):
    s = make_sidebar(self.m, True, ip="255.255.255.255")
    s._update_ip()
    s._draw_network_indicator(self.m.rl.Rectangle(0, 0, 300, 1080))
    text = [c for c in self.calls if c[0] == "text"][0]
    self.assertLess(text[4], 30)
    self.assertLessEqual(len(text[1]) * text[4] * 0.55, 240 + 1)

  def test_turning_it_off_restores_the_dots_next_update(self):
    s = make_sidebar(self.m, True)
    s._update_ip()
    s._ip_gate.on = False
    s._update_ip()
    self.assertEqual(s._ip_text, "")

  def test_sidebar_without_the_gate_still_works(self):
    s = self.m.Sidebar.__new__(self.m.Sidebar)
    s._update_ip()
    self.assertEqual(getattr(s, "_ip_text", ""), "")


if __name__ == "__main__":
  unittest.main()
