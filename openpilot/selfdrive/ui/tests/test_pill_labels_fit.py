"""Pill labels that used to overrun their pills (measured at 40 px Inter Medium, the MultipleButtonAction font)."""
from unittest import mock

import pyray as rl
import pytest

from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.bogpilot import phase3_stopping_settings as S
from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as L
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as SC


def test_weather_pill_says_low_vis_and_keeps_stored_values():
  assert S.WEATHER_PILL_LABELS == ("Clear", "Low Vis", "Rain", "Storm", "Snow")
  assert len(S.WEATHER_PILL_LABELS) == len(S.MANUAL_WEATHER)   # one label per stored value, same order
  assert S.WEATHER_PILL_WIDTH >= 160                          # "Low Vis" is ~150 px


def test_selector_pills_fit_standard():
  assert L.CHOICE_PILL_WIDTH >= 190                           # "Standard" is ~176 px
  for key in ("AccelerationProfile", "DecelerationProfile"):
    row = [r for r in L.ROWS if r.key == key][0]
    assert "Standard" in row.choices                          # the full word, not abbreviated


def test_slc_choice_pills_sized_per_label():
  labels = [lbl for opts in SC.CHOICES.values() for lbl in opts]
  assert set(labels) == set(SC.CHOICE_PILL_WIDTHS)               # every SLC choice label has its own width
  assert SC.CHOICE_PILL_WIDTHS["Experimental Mode"] >= 400        # ~371 px
  assert SC.CHOICE_PILL_WIDTHS["Set With Gas Pedal"] >= 400       # ~368 px
  for opts in SC.CHOICES.values():                                 # the row still fits next to its title
    assert sum(SC.CHOICE_PILL_WIDTHS[o] for o in opts) + 20 * (len(opts) - 1) <= 1100


@pytest.fixture
def no_window_fonts():
  # Widgets look up fonts at construction; no window is opened (same patch as test_bogpilot_gated_actions.py).
  with mock.patch.object(gui_app, "font", lambda *a, **k: rl.Font()):
    yield


def test_per_button_widths_layout_and_tap(no_window_fonts):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedMultipleButtonAction
  taps = []
  a = GatedMultipleButtonAction(["None", "Set With Gas Pedal", "Max Set Speed"], 300, 0, callback=taps.append,
                                button_widths=[200, 420, 340])
  assert a.get_width_hint() == 200 + 420 + 340 + 2 * 20
  rect = rl.Rectangle(0, 0, 1000, 100)
  assert [(r.x, r.width) for r in a.button_rects(rect)] == [(0, 200), (220, 420), (660, 340)]
  a.set_rect(rect)
  a._handle_mouse_release(rl.Vector2(430, 50))
  assert taps == [1] and a.get_selected_button() == 1
  locked = GatedMultipleButtonAction(["A", "B"], 300, 0, callback=taps.append, enabled=False, button_widths=[200, 200])
  locked.set_rect(rl.Rectangle(0, 0, 420, 100))
  locked._handle_mouse_release(rl.Vector2(300, 50))
  assert taps == [1]                                               # a locked row ignores taps


def test_stock_selector_unchanged_without_widths(no_window_fonts):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedMultipleButtonAction
  a = GatedMultipleButtonAction(["Left", "Right"], 200, 0)
  assert a.get_width_hint() == 2 * 200 + 20


def test_slc_steppers_use_plain_minus_plus():
  import inspect
  src = inspect.getsource(SC.make_layout)       # STEP_CHROME is local to make_layout
  assert '"offset": ("-", "+", 220)' in src and '"seconds": ("-", "+", 260)' in src
  assert '"priority": ("Prev", "Next", 260)' in src   # not a +/-N stepper, unchanged
  assert '"-1"' not in src and '"+1"' not in src


def test_screen_recorder_buttons_say_start_stop():
  from pathlib import Path
  from openpilot.selfdrive.ui.bogpilot import phase3_device_controls as D
  src = Path(D.__file__).read_text()
  assert 'tr("Start")' in src and 'tr("Stop")' in src          # labels only; actions unchanged
  assert "Start Recording" not in src and "Stop Recording" not in src
  assert '"action": "start_recording"' in src and '"action": "stop_recording"' in src
