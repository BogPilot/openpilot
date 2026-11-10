"""BogPilot > Vehicle Settings > Stalk Controls (supported AP1 only).

No global rename of other brands' Wheel Controls. Parent owns navigation.
"""
from opendbc.car.tesla_ap1.phase3_stalk_controls import Store, supported, experimental_supported, hold_seconds

TITLES = {
  'twist_follow': 'Stalk Twist Following Distance',
  'experimental_pull': 'Long Pull: Experimental Mode',
  'experimental_push': 'Long Push: Experimental Mode',
}
DESCRIPTIONS = {
  'twist_follow': 'Use the AP1 distance-stalk twist detent for following time. Off uses the normal driving profile. '
                  'Does not change engagement, cancel, or stalk speed steps.',
  'experimental_pull': 'While already engaged, hold the stalk toward you to flip Experimental Mode once. '
                       'The engagement pull itself never flips modes. Stock resume/set-speed behavior is unchanged.',
  'experimental_push': 'While already disengaged, hold the stalk away to flip Experimental Mode once. '
                       'A push that begins engaged still cancels immediately and never flips modes on that hold.',
}


class StalkMenu:
  def __init__(self, cp, offroad, store=None):
    self.cp, self.offroad = cp, offroad
    self.store = store if store is not None else Store()

  def visible(self, key):
    return supported(self.cp()) if key == 'twist_follow' else experimental_supported(self.cp())

  def enabled(self, key):
    return self.visible(key) and bool(self.offroad())

  def write(self, key, value):
    if not self.enabled(key):
      return False
    self.store.write(key, value)
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
  from openpilot.system.ui.widgets.list_view import ListItem, DualButtonAction, toggle_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  class StalkControlsLayout(Widget):
    def __init__(self):
      super().__init__()
      self.model = StalkMenu(lambda: ui_state.CP, ui_state.is_offroad, store)
      self.settings = self.model.store.read()
      self.toggles = {key: toggle_item(lambda k=key: tr(TITLES[k]), lambda k=key: tr(DESCRIPTIONS[k]),
                                     getattr(self.settings, key), callback=lambda value, k=key: self.set_value(k, value),
                                     enabled=lambda k=key: self.model.enabled(k)) for key in TITLES}
      self.delays = {}
      for key, label in [('pull_hold_s', 'Experimental Pull Hold'), ('push_hold_s', 'Experimental Push Hold')]:
        action = DualButtonAction('−0.01 s', '+0.01 s',
                                  lambda k=key: self.step(k, -1), lambda k=key: self.step(k, 1),
                                  enabled=lambda k=key: self.model.enabled(k))
        self.delays[key] = ListItem(title=lambda k=key, l=label: f'{tr(l)}: {getattr(self.settings, k):.2f} s',
                                   description=tr('1.10–5.00 seconds, in 0.01-second steps. Default 1.23 seconds. '
                                                  'Only Experimental Mode timing changes; normal engagement and cancel stay fixed.'),
                                   action_item=action)
      self.note = text_item(tr('Standard Stalk Engagement / Cancel'), tr('Fixed'),
                            tr('Pre-AP double-pull is not supported by this build. No engagement timing is adjustable here.'))
      for key, item in {**self.toggles, **self.delays, 'standard_engage_cancel_fixed': self.note}.items():
        attach_help(item, key)
      self.scroller = Scroller([self.toggles['twist_follow'], self.toggles['experimental_pull'], self.delays['pull_hold_s'],
                                self.toggles['experimental_push'], self.delays['push_hold_s'], self.note],
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
      self.note.set_visible(supported(ui_state.CP))

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      self.refresh()

    def _render(self, rect):
      self.refresh()
      self.scroller.render(rect)

  return StalkControlsLayout()
