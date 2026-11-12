# Divergence: AP1 engage set and IC set digit under openpilot longitudinal

Entries in the `docs/tesla/DIVERGENCES.md` style, kept in their own file so they can be folded into `DIVERGENCES.md`.
The IC set digit is `DAS_accSpeedLimit` on 0x389 (`cluster.py`), from `hudControl.setSpeed` = `carState.vCruiseCluster`
(`controlsd.py`), which `card.py` lifts with `cluster_set_kph` / `EngageClusterFloor` (`phase3_speed_control.py`).
`DAS_setSpeed` on 0x2B9 is not a set (`actuator_plan.py`: `max(v_ego + a * k, 0)`) and is unchanged.

### AP1: gas-held engage, the lateral-only pass-through is floored at vEgo
- Platforms: AP1 Model S/X with openpilot long (`Ap1SpeedControl`; Pre-AP shares the class and gets the same floor).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) started the software set at vEgo on engage, then raised to the SLC
  target (the same reference as the existing long-branch floor in `Ap1SpeedControl.update`). Tinkla/BogGyver `501c7de`
  latches vEgoRaw at engage (`ACC_module.py:154-158`). NAP `e99f4dc75`: no AP1 path.
- Our behavior: while cruise is on and openpilot longitudinal is not active yet (gas held through the engage, or the
  ticks before `longActive` is seen), `Ap1SpeedControl.update` still passes `carState.vCruise` through, but now floored
  at vEgo, the same floor the long branch applies once `longActive` rises. Raises only; a set above vEgo passes as is.
- Why: without the openpilot-long set latch, that pass-through is `DI_cruiseSet`, about half of ego under openpilot
  long, and the plan set (and the IC lift from it) showed it for as long as the gas was held.
- Safety-relevant: no. Planner set only while longitudinal is not active; no CAN, panda or DBC change.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_speed_control_pull_modes.py`
  (`test_gas_held_engage_never_passes_the_half_di_seed`, `test_di_seed_below_vego_does_not_become_the_set`).
- Credits: BogPilot 0.9.7 (engage at vEgo); Tinkla/BogGyver (vEgo latch).

### AP1: the IC engage floor arms only on the enable edge
- Platforms: AP1 Model S/X with openpilot long (`card.py` `ap1_cluster_lift`; not Pre-AP).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) has no engage floor: the IC set followed the planner set when higher
  (`cluster_display_kph`), so a down tip always showed. Tinkla/BogGyver `501c7de` shows its own set. NAP: no AP1 path.
- Our behavior: `EngageClusterFloor` holds the IC set at least at vEgo from the enable edge until the plan set reaches
  vEgo, then stays released until the next enable edge, as its docstring says. It used to re-arm on every enabled
  tick, so after a down tip below vEgo the IC showed vEgo (for example 20.9) instead of the tipped set (20).
- Safety-relevant: no. Display only; the planner set and CAN control are unchanged.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_speed_control.py`
  (`test_engage_cluster_floor_arms_only_on_the_enable_edge`, `test_engage_cluster_floor_releases_once_plan_catches_up`).
- Credits: BogPilot 0.9.7 (`cluster_display_kph`).

### AP1: 0x389 keeps the last nonzero openpilot set while enabled
- Platforms: AP1 Model S/X with IC integration (`ClusterController`, `cluster.py`).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) and this port overlay openpilot's set on `DAS_accSpeedLimit` while
  enabled and fall back to the stock value when the set is missing. Tinkla/BogGyver `501c7de`: own set on the IC. NAP: none.
- Our behavior: while enabled, when the set is momentarily missing (`cruise_set_mph` None or 0, for example an unset
  vCruise at a standstill engage), the last nonzero openpilot set of this engagement stays on the digit instead of the
  stock value. Before the first set of an engagement, and after a disengage, the stock value is kept as before.
- Why: the stock value under openpilot long can be 0 or the DI set, so the IC digit flashed 0 or a low value.
- Safety-relevant: no. Display only; DBC factor, other DAS_status2 fields and control frames unchanged.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_ap1_cluster_dbc.py` (`test_controller_keeps_last_nonzero_set_while_enabled`).
- Credits: BogPilot 0.9.7 (IC set overlay); Tinkla/BogGyver (IC integration).

### AP1: the IC set does not follow the curve-speed cap
- Platforms: AP1 Model S/X with openpilot long (`card.py` `ap1_cluster_lift`; not Pre-AP).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) `cluster_display_kph` is meant to never lower the displayed set for
  curve-speed slowdowns; 0.9.7 lifted the IC from the plan set. Tinkla/BogGyver `501c7de`: own set. NAP: no AP1 path.
- Our behavior: while `bogpilotPlan.cscControllingSpeed` is set, the IC lift (`cluster_set_kph`) uses the last plan set
  from before the curve cap (`CurveDisplayHold`, `phase3_speed_control.py`) instead of the capped `bogpilotPlan.vCruise`.
  Without the curve cap, the plan set shows as before (tips and SLC changes). Cleared on disengage.
- Why: confirmed on logs with no stalk, gas or SLC input: the plan set equaled `cscSpeed` with `cscControllingSpeed` on
  for the whole drift (40 -> 38.9 -> 37.0 and 30 -> 20.3 -> 18.8 mph), and the IC set followed it one tick later.
  The capped plan passed through because the cluster base under openpilot long sat below it.
- Limits: a stalk tip during a curve shows when the curve cap releases. The planner target is unchanged.
- Safety-relevant: no. Display only.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_speed_control.py` (`TestCurveDisplayHold`).
- Credits: BogPilot 0.9.7 (`cluster_display_kph`, curve speed control).

### AP1: under openpilot long the IC shows the plan set, floored at the engage set only until the plan reaches it
- Platforms: AP1 Model S/X with openpilot long (`card.py` `ap1_cluster_lift`; not Pre-AP).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) lifted the IC from the plan set over a DI-based cluster base
  (`cluster_display_kph`, max of the two); that base was low, so down tips showed. Tinkla/BogGyver `501c7de` shows its
  own set, including stalk changes. NAP: no AP1 path.
- Our behavior: with the openpilot-long engage set (`op_long_set_speed.py`) the cluster base is that set, so the max
  hid every down tip and SLC drop below it (replay: a DN tip to 20 showed the 30 engage set). Now, from the enable edge,
  `EngageClusterFloor` holds the IC at max(vEgo, engage set) until the plan reaches it or the driver tips the stalk, then
  `cluster_set_kph(follow_plan=True)` shows the fresh plan set as is (with the curve hold above). Stock AP and Pre-AP
  keep the max lift.
- Safety-relevant: no. Display only.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_speed_control.py` (`TestOpLongClusterFollowsPlan`).
- Credits: BogPilot 0.9.7 (`cluster_display_kph`); Tinkla/BogGyver (IC shows openpilot's set).

### AP1: the planner reads the unlifted cluster set (display lift is display-only)
- Our behavior: on AP1 Model S/X with openpilot long (the cars where the card lifts `carState.vCruiseCluster` for the
  IC: engage floor, curve hold, plan follow), `Ap1SpeedControl.update` builds `v_cruise_cluster` / `v_cruise_diff` for
  the SLC override (`update_override`) from `unlifted_cluster_kph(carState)`: the value `VCruiseHelper` had before the
  lift (pcmCruise branch: `cruiseState.speedCluster`, 0 -> `speed`; UNSET 255 / -1 as in `cruise.py`). Other cars,
  including Pre-AP, keep `carState.vCruiseCluster`. No schema change.
- Why: the lifted IC value came from the planner's own previous set (`bogpilotPlan`), so feeding it back into the
  override upper bound (`v_cruise + v_cruise_diff`) was a feedback loop from display to plan.
- Diverges from BogPilot 0.9.7 (`568fea947`): there `frogpilot_vcruise.py:48-49` built `v_cruise_diff` from
  `controlsState.vCruiseCluster`, which `controlsd.py:589` had already lifted with `cluster_display_kph`, so 0.9.7 had
  the same display-to-plan path. FrogPilot's formula is kept; only its input is the unlifted value. comma.ai openpilot
  `VCruiseHelper` for the unlifted value.
- Tests: `TestPlannerClusterUnlifted` (`test_phase3_speed_control.py`): override inputs and outputs are identical with
  the IC lifted to 150-254 kph and unlifted; `run()` now fills `cruiseState.speed` / `vCruise` from the set.
- Credits: BogPilot 0.9.7, FrogPilot (SLC override), comma.ai openpilot (`VCruiseHelper`).
