# UI divergence: gated list actions for locked BogPilot settings rows

Not a product. No warranty. Driver remains responsible. This note records a UI divergence; it changes no signal, CAN
frame, panda check or control path, and invents no signal.

Recorded only where the cited files were read. Written in the style of `docs/tesla/DIVERGENCES.md` (bogpilot-tesla);
fold it into that file when the trees meet.

## Stock v0.11.2 list actions vs BogPilot settings rows

Stock openpilot v0.11.2 (`f7db927c7`, `openpilot/system/ui/widgets/list_view.py`; the rc8 copy keeps the
`DualButtonAction` and `MultipleButtonAction` code byte-identical, BogPilot only adds `ListItem` help/level/indent):

- `DualButtonAction` builds its two `Button`s enabled and never passes its own `enabled` to them. A `Button` gates
  touches on its own `enabled` (`system/ui/widgets/__init__.py`, `Widget.render`), so a dual row "locked" with
  `enabled=` still looks live and still fires its callbacks.
- `MultipleButtonAction` is always built `enabled=True`. `_handle_mouse_release` sets `selected_button` before it calls
  the callback and has no enabled check, so a caller that locks only the `ListItem` gets a live row whose highlight can
  move to a choice that was never stored.

Stock panels are not affected in practice (`layouts/settings/device.py` re-checks `engaged` in its prompts;
`toggles.py` and `developer.py` lock `action_item`).

BogPilot rc8 (`openpilot/selfdrive/ui/bogpilot/gated_actions.py`):

- `GatedDualButtonAction(DualButtonAction)`: each button's `enabled` follows the action's `enabled` every frame
  (dimmed and touch-gated), and both callbacks are wrapped so they do nothing while the action is locked.
- `GatedMultipleButtonAction(MultipleButtonAction)`: takes an `enabled` lock, ignores releases while locked (no
  callback, no highlight move), and with `selected_source` shows the stored choice every frame and after each tap.
  Unlocked taps without `selected_source` behave exactly like stock.
- `gated_dual_button_item` / `gated_multiple_button_item`: same signatures as the stock factories plus `enabled` /
  `selected_source`; they return a stock `ListItem`.
- Used by every BogPilot settings panel with a dual or multiple row: SLC (`phase3_speed_control_settings.py`), long
  accel, following, stalk controls, stopping, steering tuning, lane change, alert volumes. Stock `device.py` and
  `toggles.py` keep the stock actions. `selfdrive/ui/tests/test_bogpilot_gated_actions.py` fails if a BogPilot panel
  goes back to a stock dual/multiple action or builds a gated row without a lock.

**Why diverge.** A locked-row audit of the previous release baseline: 10 BogPilot rows looked and acted enabled
while onroad (rows 1-4, 6, 8, 9, 15, 17, 19), and rows 1, 17 and 19 could leave a wrong value highlighted. No row wrote
a Param, because every BogPilot editor re-checks offroad/visibility at write time. That is unchanged: the gate here
only adds refusals in front of the editors' own checks, so writes stay refused onroad by the same code as before.

**Why a subclass, not a stock edit.** Maintainer decision: `system/ui/widgets/list_view.py` stays as upstream
ships it (rebases carry no BogPilot hunk in the action classes). Cost: the subclasses rely on stock attribute names
(`left_button`, `right_button`, `button_width`, `selected_button`, `_click_callback`); the tests catch a rename.

**Not in this change: lane `ui-polish-t1361`.** That lane edits stock `list_view.py` for its stepper, `button_spacing`
and shrink-to-fit labels. If the lane is ever revisited, those belong in `GatedMultipleButtonAction` (or a subclass of
it) rather than in `list_view.py`. Revisiting it needs the maintainer's ask first.

**Sources.** Stock openpilot v0.11.2 `f7db927c7` (`list_view.py`, `widgets/__init__.py`, `widgets/button.py`); BogPilot
previous release baseline `27e82a496` panels (cited in the audit). Tinkla/BogGyver and NAP use the Qt UI and were not read for this; no
claim is made about them.

## Value rows: default hint, changed highlight, section reset (rc9 UI-unify M1)

BogPilot rc9 (`openpilot/selfdrive/ui/bogpilot/gated_actions.py`, `step_defaults.py`):

- `gated_value_step_item` / `GatedValueStepAction(GatedMultipleButtonAction)`: one row `[leading] [-] [value] [+] [trailing]`, the Alert Volume layout. Lock, dim, ignored taps and hidden state are inherited unchanged from the gated list actions. The value button ignores taps. Minus is ASCII `-` (U+002D), because the Inter atlas has no U+2212.
- Default hint: a small grey `default: X` (row-description grey) under the value. X comes from the panel's existing default table. No default or param is defined here.
- Changed highlight: an outline around the value while the stored value is not the default (numbers compare by value; an unknown value, including NaN, is not highlighted).
- `reset_section_item`: one "Reset section to defaults" row per section, with no per-row Default button (option B). A tap opens a confirm dialog. Only a yes writes, and it writes only the section's own keys, through the section's own writer. The lock is checked at the tap and again at the yes. It is locked onroad like the other gated rows. It is shown only with its section (same parent switch and Tuning Level). If a write fails, the reset stops at that key and an OK dialog says so.
- First user: Alert Volume. Resets the 7 volume keys to `BOGPILOT_VOLUME_DEFAULTS` (Auto). It doesn't reset AlertVolumeControl or the PreMute restore files. The reset row uses the AlertVolumeControl Tuning Level (level 2, `bogpilot_defaults.py`).
- Steering Tuning (`phase3_steering_tuning.py`): the same shared value row, grey default hint and changed highlight, and two section Reset rows (Advanced Lateral Tuning, Quality of Life). There are no per-row RESET buttons. Each section Reset covers the value rows only, matching Alert Volume: Advanced writes `SteerDelay` / `SteerFriction` / `SteerLatAccel` / `SteerRatio` back to the existing `numeric_rows` defaults (`controls/lib/phase3_steering_tuning.py:47-57`); Quality of Life writes `PauseLateralSpeed` back to its registry default 0 (`bogpilot_params.py:297`). Toggles stay out of both section Resets (Force Auto-Tune On/Off, Turn Signal Only, and the parent switches), as Alert Volume leaves the `AlertVolumeControl` switch out (`phase2_sounds.py:114-115,120,315`). Override Sensitivity keeps its hint (`SENSITIVITY_DEFAULT` 3, `opendbc tesla_ap1/override.py:77`) but is in neither section: it is shown only for legacy Teslas and has no parent toggle, so it cannot join Advanced (parent `AdvancedLateralTune`, level 3) or Quality of Life (parent `QOLLateral`, level 1) without changing gating. After the per-row RESET is removed it has no reset. Each reset row is shown only with its value rows and behind its parent toggle's Tuning Level. Locked keys are skipped; a refused write shows the failed-reset dialog. The unlabeled level-0 -/+ row that used to appear next to the hidden Pause Steering Below label is hidden (stricter). Credits: BogPilot rc8 and stock openpilot v0.11.2 `list_view.py` / `confirm_dialog.py`.

**Why diverge.** It gives one look for every tuning value row and makes non-default values visible, with no change to ranges, write paths, signals, CAN, panda or control. Stock `list_view.py` stays byte-identical (D2 option 2).

**Sources.** BogPilot rc8 Alert Volume row (`phase2_sounds.py`) and the gated list actions; stock openpilot v0.11.2 `list_view.py` / `confirm_dialog.py`. Tinkla/BogGyver and NAP use the Qt UI and were not read for this; no claim is made about them.
