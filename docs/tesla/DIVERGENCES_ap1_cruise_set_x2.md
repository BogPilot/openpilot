# Divergence: AP1 DI_cruiseSet x2 decode correction

Entry in the `docs/tesla/DIVERGENCES.md` style, kept in its own file so it can be folded into `DIVERGENCES.md`.

### AP1: DI_cruiseSet is read at twice the DBC-decoded value (default ON)
- Platforms: AP1 Model S and Model X (`tesla_ap1/carstate.py`). Effective only with openpilot long off (stock AP): with
  openpilot long on, `cruiseState.speed` is openpilot's own set (`op_long_set_speed.py`) and never `DI_cruiseSet`.
  Pre-AP (own CarState) and the panda are unchanged.
- Reference behavior: BogPilot branch `bogpilot-tesla-cruise-half-fix` `06180370a` (opt-in x2, `cruise_set.py`),
  `0d7a29610` (default ON, missing file = x2) and `ec39be533` (scale set in `CarState.__init__`), 0.9.7 layout.
  BogPilot 0.9.7 `568fea947` and Tinkla/BogGyver `501c7de` read `DI_cruiseSet` with the DBC factor 0.5. NAP: no AP1 path.
- Our behavior: `cruiseState.speed = DI_cruiseSet * cruise_set_scale` in both unit branches; the scale is 2.0 unless
  `/data/params_bogpilot/TeslaCruiseSetScaleFix` holds 0/false/off/no (any unknown text is also off, as in the source),
  read once when CarState is constructed. The DBC factor stays 0.5 (no DBC change). KPH mode is unverified on the car.
- Why: on AP1 the raw `DI_cruiseSet` is whole display units; the DBC factor 0.5 halves it, so the stock-AP set read
  about half (the source branch's evidence: raw equals `DI_analogSpeed` in mph in standby).
- Safety-relevant: no panda, DBC, 0x45 or CAN TX change; host decode multiplier on `cruiseState.speed` only.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_ap1_cruise_set.py` (ported and extended),
  `test_ap1_op_long_set_speed.py` (stock path now scale-aware).
- Credits: BogPilot (x2 decode fix).
