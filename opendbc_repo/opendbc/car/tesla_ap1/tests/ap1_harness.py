"""Synthetic controller fixture; NOT a CarInterface/panda validation harness."""
from types import SimpleNamespace
from opendbc.can.dbc import DBC as DbcFile


def decode(addr, dat):
  for name in ("tesla_ap1_can", "tesla_powertrain"):
    msg = DbcFile(name).addr_to_msg.get(addr)
    if msg is None or msg.size != len(dat):
      continue
    values = {}
    for sig in msg.sigs.values():
      raw = sig.get_raw_value(dat)
      if sig.is_signed:
        raw -= ((raw >> (sig.size - 1)) & 1) * (1 << sig.size)
      values[sig.name] = raw * sig.factor + sig.offset
    return msg.name, values
  return addr, {}


def make_controller(long=True, raw=True, fingerprint=None, safety_param=0):
  from opendbc.car.tesla_ap1.carcontroller import CarController
  from opendbc.car.tesla_ap1.values import DBC, CAR
  assert raw
  if fingerprint is None:
    fingerprint = CAR.TESLA_AP1_MODELS
  # Default safetyConfigs stays empty so existing Model S callers are unchanged.
  configs = [SimpleNamespace(safetyParam=safety_param)] if safety_param else []
  CP = SimpleNamespace(carFingerprint=fingerprint, openpilotLongitudinalControl=long, safetyConfigs=configs)
  controller = CarController(DBC[fingerprint], CP)
  update = controller.update
  controller.update = lambda CC, CS, now: update(CC.as_reader() if hasattr(CC, "as_reader") else CC, CS, now)
  return controller


def record_requests(controller):
  requests = []
  for packer in (controller.tesla_can.packer, controller.tesla_can.pt_packer):
    real = packer.make_can_msg
    def record(name, bus, values, _real=real):
      requests.append((name, dict(values), bus))
      return _real(name, bus, values)
    packer.make_can_msg = record
  return requests
