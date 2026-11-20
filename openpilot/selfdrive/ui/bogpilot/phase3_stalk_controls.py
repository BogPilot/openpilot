"""BogPilot > Vehicle Settings > Stalk Controls (supported AP1 only).

No global rename of other brands' Wheel Controls. Parent owns navigation.
"""
from opendbc.car.tesla_ap1.phase3_stalk_controls import Store, supported, experimental_supported, hold_seconds, DEFAULT_HOLD_S

TITLES = {
  'twist_follow': 'Stalk Twist Following Distance',
  'experimental_pull': 'Long Pull: Experimental Mode',
  'experimental_push': 'Long Push: Experimental Mode',
  'tip_round': 'Round Set Speed Tips',
}
DESCRIPTIONS = {
  'twist_follow': 'Use the AP1 distance-stalk twist detent for following time. Off uses the normal driving profile. '
                  'Does not change engagement, cancel, or stalk speed steps.',
  'experimental_pull': 'While already engaged, hold the stalk toward you to flip Experimental Mode once. '
                       'The engagement pull itself never flips modes. Stock resume/set-speed behavior is unchanged.',
  'experimental_push': 'While already disengaged, hold the stalk away to flip Experimental Mode once. '
                       'A push that begins engaged still cancels immediately and never flips modes on that hold.',
  'tip_round': 'Round the set speed to a whole mph (km/h with metric units) before each stalk tip. A 14.8 mph set tipped up by five '
               'goes to 20, not 15. Off tips from the exact set. Does not change engagement, cancel, or what a pull does.',
}


class StalkMenu:
  """`offroad` is the edit gate: the UI passes onroad_policy.editor("stalk_controls") (0.9.7 Wheel Controls, reboot-
  prompt class: editable while driving). `on_change(key)` runs after each saved write (the reboot prompt)."""
  def __init__(self, cp, offroad, store=None, on_change=None):
    self.cp, self.offroad = cp, offroad
    self.store = store if store is not None else Store()
    self.on_change = on_change or (lambda key: None)

  def visible(self, key):
    return supported(self.cp()) if key == 'twist_follow' else experimental_supported(self.cp())

  def enabled(self, key):
    return self.visible(key) and bool(self.offroad())

  def write(self, key, value):
    if not self.enabled(key):
      return False
    self.store.write(key, value)
    self.on_change(key)
    return True

  def step(self, key, hundredths):
    value = getattr(self.store.read(), key)
    try:
      return self.write(key, hold_seconds(round(value + hundredths / 100, 2)))
    except ValueError:
      return False


def create_stalk_controls_layout(store=None):
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item, text_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item, reset_section_item, RESET_SECTION_TITLE
  from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  class StalkControlsLayout(Widget):
    def __init__(self):
      super().__init__()
      from openpilot.selfdrive.ui.bogpilot import onroad_policy
      self.model = StalkMenu(lambda: ui_state.CP, onroad_policy.editor("stalk_controls"), store,
                             on_change=onroad_policy.on_change("stalk_controls"))
      self.settings = self.model.store.read()
      self.toggles = {key: toggle_item(lambda k=key: tr(TITLES[k]), lambda k=key: tr(DESCRIPTIONS[k]),
                                     getattr(self.settings, key), callback=lambda value, k=key: self.set_value(k, value),
                                     enabled=lambda k=key: self.model.enabled(k)) for key in TITLES}
      self.delays = {}
      def hold_text(value):
        return f"{float(value):.2f} s"
      for key, label in [('pull_hold_s', 'Experimental Pull Hold'), ('push_hold_s', 'Experimental Push Hold')]:
        # Shared value row: [-] [value] [+]. Hold range, step, and DEFAULT_HOLD_S (1.23 s) are unchanged.
        # Default source: opendbc/car/tesla_ap1/phase3_stalk_controls.py DEFAULT_HOLD_S = 1.23.
        self.delays[key] = gated_value_step_item(
          lambda l=label: tr(l),
          lambda: tr('1.10–5.00 seconds, in 0.01-second steps. '
                     'Only Experimental Mode timing changes; normal engagement and cancel stay fixed.'),
          lambda k=key: hold_text(getattr(self.settings, k)),
          lambda k=key: self.step(k, -1),
          lambda k=key: self.step(k, 1),
          enabled=lambda k=key: self.model.enabled(k),
          default_text=lambda: hold_text(DEFAULT_HOLD_S),
          is_default=lambda k=key: not differs_from_default(getattr(self.settings, k), DEFAULT_HOLD_S),
          translate=tr,
        )
      # One reset for both hold keys, gated like those rows (experimental_supported + edit gate). There is no
      # Tuning Level parent for these keys in the params registry, so no invented level gate is applied.
      def write_hold(key, value):
        if not self.model.write(key, value):
          raise PermissionError(f"{key} was not reset")
      self.reset = reset_section_item(
        # Both keys share DEFAULT_HOLD_S (opendbc/car/tesla_ap1/phase3_stalk_controls.py).
        {"pull_hold_s": DEFAULT_HOLD_S, "push_hold_s": DEFAULT_HOLD_S},
        write_hold,
        title=lambda: tr(RESET_SECTION_TITLE),
        enabled=lambda: self.model.enabled("pull_hold_s"),
        on_done=self.refresh,
      )
      self.note = text_item(tr('Standard Stalk Engagement / Cancel'), tr('Fixed'),
                            tr('Normal engage and cancel on the stalk are fixed. No engagement timing is adjustable here.'))
      for key, item in {**self.toggles, **self.delays, 'standard_engage_cancel_fixed': self.note}.items():
        attach_help(item, key)
      attach_help(self.reset, "section.reset_defaults")
      # An empty or short page says why (no car / wrong car / longitudinal control off) instead of showing nothing.
      from openpilot.selfdrive.ui.bogpilot import menu_locks
      note = menu_locks.cached(lambda: menu_locks.page_note(ui_state.CP, "stalk_controls", menu_locks.effective_disable_toggle()))
      self.note_row = menu_locks.note_row(note, "Not all rows are shown")
      self.scroller = Scroller([self.note_row, self.toggles['twist_follow'], self.toggles['tip_round'], self.toggles['experimental_pull'], self.delays['pull_hold_s'],
                                self.toggles['experimental_push'], self.delays['push_hold_s'], self.reset, self.note],
                               line_separator=True, spacing=0)

    def set_value(self, key, value):
      self.model.write(key, value)
      self.refresh()

    def step(self, key, delta):
      self.model.step(key, delta)
      self.refresh()

    def refresh(self):
      self.settings = self.model.store.read()
      for key, item in self.toggles.items():
        item.set_visible(self.model.visible(key))
        item.action_item.set_state(getattr(self.settings, key))
      for key, item in self.delays.items():
        item.set_visible(self.model.visible(key))
      self.reset.set_visible(self.model.visible("pull_hold_s"))
      self.note.set_visible(supported(ui_state.CP))

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      self.refresh()

    def _render(self, rect):
      self.refresh()
      self.scroller.render(rect)

  return StalkControlsLayout()
