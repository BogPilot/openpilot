"""StarPilot card hooks for the Tesla AP1 Model S port (BogStar). Python only, AP1 only.

No new params keys and no new cereal fields (StarPilot ships a prebuilt params module):
- Stalk follow detent -> existing LongitudinalPersonality param (selfdrived re-reads it every 0.1 s).
- Long (~2 s) RWD stalk pull while engaged -> one Experimental Mode toggle through StarPilotCard's
  existing handle_experimental_mode (respects Conditional Experimental / Conditional Chill / Safe Mode).
- modelV2 position x / y -> Ap1CarController.model_path_x / model_path_y for the cluster 0x239 path.

Ported from BogPilot bogpilot-tesla (frogpilot_card._apply_ap1_pull_hold / stalk personality and
carcontroller._model_path_for_cluster). Not a product, no warranty.
"""

from opendbc.car.tesla.values import TeslaFlags


def is_tesla_ap1(CP) -> bool:
  return CP.brand == "tesla" and bool(CP.flags & TeslaFlags.AP1)


class TeslaAp1CardHooks:
  SERVICES = ['modelV2']

  def __init__(self, params):
    self.params = params
    self.last_personality = None

  def after_state_update(self, CS_py, sm, starpilot_card, starpilot_toggles) -> None:
    # Stalk follow detent -> LongitudinalPersonality, only when the detent changes.
    personality = getattr(CS_py, "personality_request", None)
    if personality is not None and personality != self.last_personality:
      self.params.put_nonblocking("LongitudinalPersonality", int(personality))
      self.last_personality = personality

    # Long RWD pull while engaged -> one Experimental Mode toggle.
    if getattr(CS_py, "stalk_pull_toggle", False) and sm['carControl'].enabled:
      starpilot_card.handle_experimental_mode(sm, starpilot_toggles)

  @staticmethod
  def before_apply(CC_py, sm) -> None:
    x, y = [], []
    if sm.seen['modelV2'] and sm.valid['modelV2']:
      pos = sm['modelV2'].position
      x = list(pos.x)
      y = list(pos.y)
    CC_py.model_path_x = x
    CC_py.model_path_y = y
