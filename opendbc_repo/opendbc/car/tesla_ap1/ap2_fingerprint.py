"""AP2 Model S marker guard for the AP1 detection path.

Keys are CAN addresses that Tinkla's AP2 Model S capture carries and its AP1
Model S captures do not, with the length seen on that capture. Bus 0 only.

0x32B and 0x350 are also AP2-only in Tinkla's dicts but they appear on the AP1
radar bus (bus 1) in our own AP1 Model S logs, so they are not markers. No
other marker address appeared on any bus of any AP1 Model S log checked
(see docs/bogpilot_ap2_port_plan.md).

AP2 Model X has no marker: Tinkla's AP2 and AP1 Model X dicts are identical.
"""

from opendbc.car.tesla_ap1.values import CANBUS

AP2_S_ONLY = {
  0x259: 8, 0x260: 1, 0x36C: 8, 0x38A: 8, 0x3C9: 6, 0x3CB: 8, 0x3EF: 8, 0x3F0: 8,
  0x3F2: 6, 0x3F6: 1, 0x3F7: 8, 0x3F9: 8, 0x3FA: 8, 0x3FC: 8, 0x419: 8, 0x425: 8,
  0x429: 8, 0x439: 8, 0x449: 8, 0x459: 8, 0x469: 8, 0x479: 8, 0x499: 8, 0x549: 8,
  0x5C9: 8, 0x5E9: 8,
}

# A fingerprint window is short and slow messages can be missed, so the guard
# fires on a few markers instead of all of them.
AP2_S_MIN_MARKERS = 3


def ap2_s_evidence(fp) -> frozenset:
  """AP2-only addresses on bus 0 whose observed length matches Tinkla."""
  try:
    bus0 = fp.get(CANBUS.chassis)
    if not isinstance(bus0, dict):
      return frozenset()
    return frozenset(addr for addr, length in AP2_S_ONLY.items() if bus0.get(addr) == length)
  except Exception:
    return frozenset()


def looks_like_ap2_s(fp) -> bool:
  return len(ap2_s_evidence(fp)) >= AP2_S_MIN_MARKERS
