# Inert compatibility shim: BogPilot has no comma registration/athena.
# Only re-exports local constants for not-yet-migrated UI imports; remove after UI migrates
# to openpilot.system.manager.local_identity.
from openpilot.system.manager.local_identity import UNREGISTERED_DONGLE_ID, is_registered_device

__all__ = ["UNREGISTERED_DONGLE_ID", "is_registered_device"]
