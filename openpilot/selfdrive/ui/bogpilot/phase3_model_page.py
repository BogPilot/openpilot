"""BogPilot > Driving Controls > Driving Model page: real backend wiring (no Params, no inert rows).

The consumer is the modeld launcher (openpilot.common.phase3_modeld_launcher), which resolves the model
exactly once per modeld start from the transactional runtime state this page writes (offroad only).
Default (stock) is always selected on a fresh install; every failure path falls back to it.
"""
# Control ids that have a real consumer, for phase2_navigation.Page.controls.
DRIVING_MODEL_KEYS = ("driving_model_select",)


def create_driving_model_layout():
  from openpilot.common.phase3_model_backend import RuntimeModelBackend
  from openpilot.selfdrive.ui.bogpilot.phase3_model_selector import ModelSelector, create_model_selector_layout
  from openpilot.selfdrive.ui.ui_state import ui_state
  backend = RuntimeModelBackend(is_offroad=ui_state.is_offroad)
  return create_model_selector_layout(ModelSelector(backend, ui_state.is_offroad))
