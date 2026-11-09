"""BogPilot driving-model registry and selector runtime (clean-room, written for openpilot 0.11.2).

Nothing here is derived from sunnypilot or FrogPilot model-selector code. The package is import-light on
purpose: modeld's launcher imports it before anything heavy, and every public entry point either returns a
value or reports a reason; none of them raises into modeld.
"""
TARGET_OPENPILOT = "0.11.2"
STOCK_ID = "default"
STOCK_NAME = "Default (stock)"
