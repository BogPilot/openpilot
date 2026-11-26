"""Daily BogPilot DM placement using the unchanged native face/state renderer.

No synthetic runtime data or alternative driver-monitoring policy. Safety alerts
remain exclusively owned by native AlertRenderer/AlertManager.
"""
from openpilot.selfdrive.ui.onroad.bogpilot.driver_monitor_layout import placement, fresh


class DriverMonitorLayer:
  name = "driver_monitor"
  replaces = frozenset({"driver_state"})
  supports_compact = False

  def __init__(self):
    self._renderer = None
    self.bounds = None
    self._epoch = None

  def enabled(self, frame):
    if not (frame.redesign and not frame.mici and not frame.full_alert):
      return False
    # Match stock visibility exactly: any stock alert hides the face graphic.
    # Alert renderer is never replaced by this layer.
    if frame.alert is not None and frame.alert.size != 0:
      return False
    sm = getattr(frame, "sm", None)
    if not fresh(sm, getattr(frame, "now", -1), frame.started_frame, getattr(frame, "drive_start", float("inf"))):
      return False
    self.bounds = placement(frame.rect, frame.rhd, getattr(frame, "dm_personality_visible", False),
                            getattr(frame, "dm_keepouts", frame.keepouts))
    return self.bounds is not None

  def update(self, frame):
    if self._epoch != frame.started_frame:
      self.reset()
      self._epoch = frame.started_frame
    # Creation is lazy so the adapter can be discovered before raylib starts.
    if self._renderer is None:
      from openpilot.selfdrive.ui.onroad.driver_state import DriverStateRenderer
      self._renderer = DriverStateRenderer()
    self.enabled(frame)  # restore current bounds after a new-drive reset

  def draw(self, frame):
    import pyray as rl
    if self.bounds is None:
      return
    renderer = self._renderer
    renderer.set_rect(frame.rect)
    renderer._update_state()  # unchanged native policy, RHD, pose, fade and arcs
    if not renderer.is_visible:
      return
    b = self.bounds
    # Native drawing centred on its own anchor. Transform the complete face,
    # texture, arcs and line widths together to daily's 150/192 cluster size.
    centre = rl.Vector2(b.x + 75, b.y + 75)
    camera = rl.Camera2D(centre, rl.Vector2(renderer.position_x, renderer.position_y), 0, 150 / 192)
    rl.begin_mode_2d(camera)
    try:
      renderer._render(frame.rect)
    finally:
      rl.end_mode_2d()

  def reset(self):
    # Discard temporal smoothing, camera handedness and previous-drive pose.
    self._renderer = None
    self.bounds = None
    self._epoch = None


def make_layer(mici=False):
  return None if mici else DriverMonitorLayer()
