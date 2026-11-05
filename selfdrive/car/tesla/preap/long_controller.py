"""NAP-style Pre-AP pedal longitudinal controller (VirtualDAS + authority).

Credit: NAP-style. Software-only GAS_SENSOR handshake; no panda loosening.
Passive BogPilot PedalCalib* stays; di_to_pedal uses current_pedal_transform.
"""
from __future__ import annotations

import logging
import math

from openpilot.common.params import Params
from openpilot.selfdrive.car.tesla.preap.accel_limits import get_preap_accel_limits
from openpilot.selfdrive.car.tesla.preap.pedal_authority import (
  ENGAGE_GRACE_FRAMES,
  ENGAGE_GRACE_PEDAL_RAMP_RATE_UP,
  PedalAuthority,
  PedalAuthorityState,
  PedalCommandAction,
  RegenDecelMonitor,
)
from openpilot.selfdrive.car.tesla.preap.pedal_can import create_pedal_command
from openpilot.selfdrive.car.tesla.preap.pedal_controller import (
  di_to_pedal,
  get_zero_torque,
)
from openpilot.selfdrive.car.tesla.preap.vdas_constants import PEDAL_RAMP_RATE_UP
from openpilot.selfdrive.car.tesla.preap.virtual_das import VirtualDAS

_log = logging.getLogger("preap.long")


class PreAPLongController:
  """Pedal-mode longitudinal: VirtualDAS, zero-torque, command authority.

  Stalk-CC spoofs (CANCEL) stay in StockCCSpoofer via CarState flags.
  """

  def __init__(self, pedal_counter, pedal_bus_fn):
    self.prev_pedal_di = 0.0
    self.prev_requested_long = False
    self.preap_long_engage_frame = -1000000
    self.engage_a_max = 0.0
    self.preap_long_handoff_slew_active = False
    self.vdas = VirtualDAS(dt=0.02)
    self.pedal_authority = PedalAuthority()
    self.regen_decel_monitor = RegenDecelMonitor()
    self.pedal_counter = pedal_counter
    self._pedal_bus_fn = pedal_bus_fn
    self._params = Params()

  def _append_pedal_command(self, can_sends, CS, pedal_cmd: float, enable: int):
    cmd = create_pedal_command(pedal_cmd, enable, self.pedal_counter, self._pedal_bus_fn())
    can_sends.append(cmd)
    # cmd = (addr, 0, dat, bus); counter lives in dat[4] low nibble
    try:
      CS.pedal_command_counter = cmd[2][4] & 0x0F
    except Exception:
      pass

  def _personality(self) -> int:
    try:
      raw = self._params.get("LongitudinalPersonality", encoding=None)
      if raw is None:
        return 1
      if isinstance(raw, (bytes, bytearray)):
        return int(raw.decode("utf-8") or "1")
      return int(raw)
    except Exception:
      return 1

  def update(self, CC, CS, frame, *, long_ok: bool, now_nanos: int = 0):
    """Append pedal CAN frames for this control step. Returns can_sends list."""
    can_sends = []
    actuators = CC.actuators

    # BogPilot: requested_long from CC.enabled + longActive + gating (no NAP
    # engagement FSM / double-pull). BogPilot uses CC.enabled+longActive (no NAP engagement FSM).
    requested_long = bool(CC.enabled) and bool(CC.longActive) and bool(long_ok)
    long_active = requested_long
    pedal_long_allowed = bool(long_ok)

    if (not long_active
        or getattr(CS, "real_brake_pressed", False)
        or getattr(CS.out, "gasPressed", False)):
      self.regen_decel_monitor.reset()

    requested_long_rising = (not self.prev_requested_long) and requested_long
    if requested_long_rising:
      zero_torque_di = get_zero_torque().get(CS.out.vEgo)
      interceptor = float(getattr(CS, "pedal_interceptor_value", 0.0) or 0.0)
      self.prev_pedal_di = max(interceptor, zero_torque_di)
      CS.pedal_first_enabled_mono_time = 0
      # Clear prior authority failure so a fresh engage can re-acquire.
      if getattr(CS, "pedal_unavailable", False):
        CS.pedal_unavailable = False
        if self.pedal_authority.state == PedalAuthorityState.FAILED:
          self.pedal_authority.state = PedalAuthorityState.INACTIVE
    elif not hasattr(CS, "pedal_first_enabled_mono_time"):
      CS.pedal_first_enabled_mono_time = 0

    # Stock CC cancel triggers (same as prior BogPilot StockCCSpoofer path)
    if pedal_long_allowed:
      cruise_btn = int(getattr(CS, "cruise_buttons", 0) or 0)
      prev_btn = int(getattr(CS, "prev_cruise_buttons", 0) or 0)
      pedal_button_press = (cruise_btn != prev_btn) and (cruise_btn != 0)
      pedal_long_falling = self.prev_requested_long and not requested_long
      if requested_long_rising or pedal_long_falling or pedal_button_press:
        CS.preap_cc_cancel_needed = True

    self.prev_requested_long = requested_long

    # 50 Hz pedal path (even frames), matching NAP
    if frame % 2 == 0:
      brake_pressed = bool(getattr(CS, "real_brake_pressed", False))
      gas_pressed = bool(getattr(CS.out, "gasPressed", False))
      authority_requested = (
        pedal_long_allowed and long_active and not brake_pressed and not gas_pressed
        and not bool(getattr(CS, "pedal_unavailable", False))
      )
      feedback = getattr(CS, "pedal", None)
      if feedback is None:
        # Should be wired by carstate; fail soft to inactive.
        from openpilot.selfdrive.car.tesla.preap.pedal_feedback import PedalFeedback
        feedback = PedalFeedback()
        CS.pedal = feedback

      pedal_action = self.pedal_authority.update(authority_requested, feedback)
      in_engage_grace = False

      if pedal_action == PedalCommandAction.ACQUIRE:
        self.preap_long_engage_frame = frame
        self.preap_long_handoff_slew_active = True
        zero_torque_di = get_zero_torque().get(CS.out.vEgo)
        interceptor = float(getattr(CS, "pedal_interceptor_value", 0.0) or 0.0)
        self.prev_pedal_di = max(interceptor, zero_torque_di)
        self.vdas.reset(
          measured_accel=CS.out.aEgo,
          commanded_accel=0.0,
          pedal_di_init=self.prev_pedal_di,
          preserve_grade=True,
        )
        _, self.engage_a_max = get_preap_accel_limits(CS.out.vEgo, self._personality())

      orientation = list(getattr(CC, "orientationNED", None) or [])
      if pedal_long_allowed and pedal_action not in (
        PedalCommandAction.ACQUIRE, PedalCommandAction.ENABLE,
      ):
        self.vdas.observe(CS.out.aEgo, orientation)

      if pedal_long_allowed:
        get_zero_torque().update(
          float(getattr(feedback, "torque_level", 0.0) or 0.0),
          self.prev_pedal_di,
          CS.out.vEgo,
          control_active=pedal_action in (
            PedalCommandAction.ACQUIRE, PedalCommandAction.ENABLE,
          ),
          accel_command=self.vdas.jerk_limiter.a_limited,
        )

      if pedal_action == PedalCommandAction.RESET:
        self._append_pedal_command(can_sends, CS, 0.0, 0)
        self.preap_long_handoff_slew_active = False
        self.regen_decel_monitor.reset()

      elif pedal_action == PedalCommandAction.RELEASE:
        self._append_pedal_command(can_sends, CS, 0.0, 0)
        self.prev_pedal_di = 0.0
        self.preap_long_handoff_slew_active = False
        self.regen_decel_monitor.reset()

      elif pedal_action in (PedalCommandAction.ACQUIRE, PedalCommandAction.ENABLE):
        try:
          engage_elapsed_frames = frame - self.preap_long_engage_frame
          in_engage_grace = engage_elapsed_frames < ENGAGE_GRACE_FRAMES
          accel_request = float(actuators.accel)
          accel_effort_limits = None
          pedal_ramp_rate_up = (
            ENGAGE_GRACE_PEDAL_RAMP_RATE_UP
            if self.preap_long_handoff_slew_active
            else PEDAL_RAMP_RATE_UP
          )
          if in_engage_grace:
            grace_progress = engage_elapsed_frames / ENGAGE_GRACE_FRAMES
            accel_cap = grace_progress * self.engage_a_max
            accel_request = max(0.0, min(accel_request, accel_cap))
            accel_effort_limits = (0.0, accel_cap)
            pedal_ramp_rate_up = ENGAGE_GRACE_PEDAL_RAMP_RATE_UP

          self.prev_pedal_di = self.vdas.update(
            accel_request, CS.out.vEgo, self.prev_pedal_di,
            a_ego=CS.out.aEgo, freeze_integrator=in_engage_grace,
            orientation_ned=orientation,
            accel_effort_limits=accel_effort_limits,
            pedal_ramp_rate_up=pedal_ramp_rate_up,
          )
          handoff_slew_complete = (
            self.preap_long_handoff_slew_active
            and not in_engage_grace
            and not self.vdas.pedal_ramp_limited_up
          )
          if handoff_slew_complete:
            self.preap_long_handoff_slew_active = False

          pedal_cmd = di_to_pedal(self.prev_pedal_di)
          if not math.isfinite(pedal_cmd):
            raise ValueError("non-finite pedal command")
          self._append_pedal_command(can_sends, CS, float(pedal_cmd), 1)
          if pedal_action == PedalCommandAction.ACQUIRE and CS.pedal_first_enabled_mono_time == 0:
            CS.pedal_first_enabled_mono_time = now_nanos
          self.regen_decel_monitor.update(
            pedal_control_active=True,
            in_engage_grace=in_engage_grace,
            pedal_di=self.prev_pedal_di,
            limited_accel=self.vdas.jerk_limiter.a_limited,
            actual_accel=CS.out.aEgo,
            v_ego=CS.out.vEgo,
          )

        except Exception:
          _log.exception("Pre-AP pedal command failed; sending disabled")
          self.pedal_authority.command_failed()
          CS.pedal_unavailable = True
          self._append_pedal_command(can_sends, CS, 0.0, 0)
          self.prev_pedal_di = 0.0
          self.preap_long_handoff_slew_active = False
          self.regen_decel_monitor.reset()
          pedal_action = PedalCommandAction.FAILURE

      elif pedal_action == PedalCommandAction.FAILURE:
        _log.error("Pre-AP pedal authority acquisition failed")
        CS.pedal_unavailable = True
        self.preap_long_handoff_slew_active = False
        self.regen_decel_monitor.reset()

      else:
        self.regen_decel_monitor.reset()

      CS.pedal_authority_requested = authority_requested
      CS.pedal_authority_active = (
        self.pedal_authority.state == PedalAuthorityState.ACTIVE
        and not bool(getattr(CS, "pedal_unavailable", False))
      )
      CS.pedal_authority_state = int(self.pedal_authority.state)
      CS.pedal_authority_action = int(pedal_action)

    CS.vdas_limited_accel = float(self.vdas.jerk_limiter.a_limited)
    CS.pedal_command_di = float(self.prev_pedal_di)
    CS.pedal_brake_required = bool(self.regen_decel_monitor.active)
    return can_sends
