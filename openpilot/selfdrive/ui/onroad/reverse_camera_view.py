"""Onroad driver camera shown while reversing. Reuses the existing cabin view drawing (face box + DM icon)
without its manual-preview side effects: no IsDriverViewEnabled write, no pop-on-tap, no timeout callback."""
from openpilot.cereal.visionipc import VisionStreamType
from openpilot.selfdrive.ui.onroad.cabin_camera_dialog import CabinCameraDialog
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.selfdrive.ui.onroad.driver_state import DriverStateRenderer


class ReverseDriverCameraView(CabinCameraDialog):
  def __init__(self):  # deliberately not CabinCameraDialog.__init__
    CameraView.__init__(self, "camerad", VisionStreamType.VISION_STREAM_CABIN)
    self.driver_state_renderer = DriverStateRenderer()

  def hide_event(self):
    CameraView.hide_event(self)

  def _handle_mouse_release(self, _):
    pass  # 0.9.7 ignored touches while the reverse view was up
