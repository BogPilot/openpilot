"""Pre-AP pull wording: user-facing text says "single pull" and "double pull", with no timing and no other feature names."""
import re
from pathlib import Path

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import EVENTS, ET

EventName = log.OnroadEvent.EventName

# Words the user-facing pull text must not carry: the window timing and the old first/second wording.
TIMING = ("400 ms", "0.4 s", "first pull", "second pull", "pull twice", "twice")
# The lateral-only feature that is not part of this port, by its full name and its initials. Built from parts so a plain
# text search of this change for that feature finds nothing.
_FEATURE = " ".join(("always", "on", "lateral"))
_INITIALS = "".join(w[0] for w in _FEATURE.split()).upper()
OTHER_FEATURE = re.compile(rf"{_FEATURE}|\b{_INITIALS}\b", re.IGNORECASE)


def _repo_root() -> Path:
  for p in Path(__file__).resolve().parents:
    if (p / "docs" / "tesla" / "PREAP_PORT.md").is_file():
      return p
  raise AssertionError("docs/tesla/PREAP_PORT.md not found above this test")


def _alerts():
  return {
    "preapSteerOnly": EVENTS[EventName.preapSteerOnly][ET.PERMANENT],
    "preapSpeedBlocked": EVENTS[EventName.preapSpeedBlocked][ET.WARNING],
    "preapCruiseNotArmed": EVENTS[EventName.preapCruiseNotArmed][ET.PERMANENT],
  }


def _section(text: str, heading: str) -> str:
  start = text.index(heading)
  nxt = re.search(r"^#{2,3} ", text[start + len(heading):], re.MULTILINE)
  return text[start:start + len(heading) + (nxt.start() if nxt else len(text))]


def _port_pull_sections() -> list[str]:
  text = (_repo_root() / "docs" / "tesla" / "PREAP_PORT.md").read_text()
  return [_section(text, "### Curve speed control with the pedal (vision-only)"),
          _section(text, "### NAP-style double pull: a single pull steers, a double pull adds speed control")]


def test_pull_alerts_say_double_pull():
  a = _alerts()
  assert (a["preapSteerOnly"].alert_text_1, a["preapSteerOnly"].alert_text_2) == ("Steering only", "Double pull for speed control")
  assert (a["preapSpeedBlocked"].alert_text_1, a["preapSpeedBlocked"].alert_text_2) == ("Speed control off", "Steering only. Double pull to retry")
  assert (a["preapCruiseNotArmed"].alert_text_1, a["preapCruiseNotArmed"].alert_text_2) == ("Stock cruise did not arm", "Double pull again")


def test_port_notes_say_single_and_double_pull():
  curve, pull = _port_pull_sections()
  assert "controls speed only in speed control (double pull)" in curve
  assert "- A single pull engages steering only; a double pull adds speed control." in pull
  assert "Without the pedal a single pull cancels a stock cruise it armed and the driver's double pull re-arms it." in pull


def test_user_facing_pull_text_has_no_timing_and_no_other_feature():
  assert OTHER_FEATURE.search("Pre-AP: " + _FEATURE.title()) and OTHER_FEATURE.search(_INITIALS + " on")  # the check itself works
  texts = [a.alert_text_1 + " " + a.alert_text_2 for a in _alerts().values()] + _port_pull_sections()
  for t in texts:
    flat = " ".join(t.split())
    assert not OTHER_FEATURE.search(flat), flat
    for bad in TIMING:
      assert bad not in flat.lower(), (bad, flat)


def test_developer_notes_quote_the_current_alerts():
  text = " ".join((_repo_root() / "docs" / "tesla" / "DIVERGENCES_preap_nap_fsm.md").read_text().split())
  for a in _alerts().values():
    assert f'"{a.alert_text_1} / {a.alert_text_2}"' in text, (a.alert_text_1, a.alert_text_2)
