"""StarPilot card hooks for the Tesla AP1 Model S port (BogStar). Python only, AP1 only.

No new params keys (StarPilot ships a prebuilt params module):
- Stalk follow detent -> existing LongitudinalPersonality param (selfdrived re-reads it every 0.1 s).
- Long (~2 s) RWD stalk pull while engaged -> one Experimental Mode toggle through StarPilotCard's
  existing handle_experimental_mode (respects Conditional Experimental / Conditional Chill / Safe Mode).
- Long (~2 s) FWD stalk hold while disengaged -> one Experimental Mode toggle (milestone 4). Same hook,
  without the engaged gate.
- Continuous stalk levels (UP / DN / RWD and raw SpdCtrlLvr_Stat) -> starpilotCarState accelPressed /
  decelPressed / resumePressed / spdCtrlLvr for the AP1 set-speed layer in starpilot_vcruise. buttonEvents
  are ~10 ms edges and the planner samples at 20 Hz, so it needs levels. resumePressed and spdCtrlLvr
  are the two Python-read cereal fields this port adds (custom.capnp StarPilotCarState @31 / @32).
- Cluster / HUD set lift to starpilotPlan.vCruise (ap1_slc_raise.cluster_display_kph).
- modelV2 position x / y -> Ap1CarController.model_path_x / model_path_y for the cluster 0x239 path.

Ported from BogPilot bogpilot-tesla (frogpilot_card._apply_ap1_pull_hold / _apply_ap1_fwd_hold /
_apply_ap1_stalk_levels / stalk personality, controlsd cluster lift and
carcontroller._model_path_for_cluster). Not a product, no warranty.
"""

from opendbc.car import structs
from opendbc.car.tesla.ap1_slc_raise import cluster_display_kph
from opendbc.car.tesla.values import TeslaFlags

ButtonType = structs.CarState.ButtonEvent.Type


def is_tesla_ap1(CP) -> bool:
  return CP.brand == "tesla" and bool(CP.flags & TeslaFlags.AP1)


class TeslaAp1CardHooks:
  SERVICES = ['modelV2']

  def __init__(self, params):
    self.params = params
    self.last_personality = None

  def after_state_update(self, CS_py, sm, starpilot_card, starpilot_toggles, FPCS=None) -> None:
    if FPCS is not None:
      self.apply_stalk_levels(CS_py, FPCS)

    # Stalk follow detent -> LongitudinalPersonality, only when the detent changes.
    personality = getattr(CS_py, "personality_request", None)
    if personality is not None and personality != self.last_personality:
      self.params.put_nonblocking("LongitudinalPersonality", int(personality))
      self.last_personality = personality

    # Long RWD pull while engaged -> one Experimental Mode toggle.
    if getattr(CS_py, "stalk_pull_toggle", False) and sm['carControl'].enabled:
      starpilot_card.handle_experimental_mode(sm, starpilot_toggles)

    # Long FWD hold while disengaged -> one Experimental Mode toggle. No engaged gate: this path must
    # work while disengaged. Cancel while engaged and short FWD presses never set the flag.
    if getattr(CS_py, "stalk_fwd_toggle", False):
      starpilot_card.handle_experimental_mode(sm, starpilot_toggles)

  @staticmethod
  def apply_stalk_levels(CS_py, FPCS) -> None:
    """Continuous UP / DN / RWD levels and raw SpdCtrlLvr_Stat onto starpilotCarState.

    accelPressed is UP only (not OR resume) so a tip-up never fires on a pull; resumePressed carries
    the pull.
    """
    bs = getattr(CS_py, "button_states", None)
    if not isinstance(bs, dict):
      return
    FPCS.accelPressed = bool(bs.get(ButtonType.accelCruise, False))
    FPCS.decelPressed = bool(bs.get(ButtonType.decelCruise, False))
    FPCS.resumePressed = bool(bs.get(ButtonType.resumeCruise, False))
    FPCS.spdCtrlLvr = int(getattr(CS_py, "spd_ctrl_lvr", 0) or 0) & 0xFF

  @staticmethod
  def cluster_set_kph(v_cruise_cluster_kph, sm) -> float:
    """Cluster / HUD set follows the AP1 planner set when it is higher (never lowered for CSC)."""
    if not sm.seen['starpilotPlan']:
      return v_cruise_cluster_kph
    return cluster_display_kph(v_cruise_cluster_kph, float(sm['starpilotPlan'].vCruise))

  @staticmethod
  def before_apply(CC_py, sm) -> None:
    x, y = [], []
    if sm.seen['modelV2'] and sm.valid['modelV2']:
      pos = sm['modelV2'].position
      x = list(pos.x)
      y = list(pos.y)
    CC_py.model_path_x = x
    CC_py.model_path_y = y
