# Stopping-lane baselines

Byte-exact copies of the BogPilot `longcontrol.py`, `longitudinal_planner.py` and `radard.py` from before the stop and gas/brake rows
were added. The equivalence tests in `test_gas_brake_stop_defaults.py`, `test_stop_rows_safe_floors.py` and
`test_phase3_stopping_consumers.py` run these against the current code to prove the defaults are unchanged.
They are test data only and are never imported by the running system. Do not edit them.
