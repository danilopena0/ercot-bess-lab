# 0006: Perfect-foresight dispatch as an LP, not a MILP

**Status:** Accepted (M2)

## Context

SPEC.md allows either an LP or MILP formulation for the perfect-foresight benchmark. A
MILP would add a binary variable per interval to forbid simultaneous charging and
discharging, at the cost of integer-programming solve time — meaningful over a full
month of 15-minute RTM intervals (2,880+ binaries).

## Decision

Formulate as a pure LP. Simultaneous charge and discharge in the same interval is never
optimal for a price-taking arbitrageur once round-trip efficiency losses and a per-MWh
degradation cost are in the objective: charging and discharging the same interval only
burns efficiency and degradation cost for zero net energy moved, which is always weakly
dominated by doing neither. The LP relaxation is therefore guaranteed to find a solution
with `charge[t] * discharge[t] == 0` for every interval without needing to enforce it as
a constraint — this is a standard result for battery arbitrage LPs, and all six
golden-case tests (`tests/test_perfect_foresight.py`) confirm it holds for the specific
formulation used here.

Round-trip efficiency is split evenly across the two legs (`BatterySpec.
one_way_efficiency = sqrt(round_trip_efficiency)`), the standard convention when only a
single RTE figure is available rather than separate charge/discharge efficiency curves.

The daily cycle limit is enforced **per calendar day** (grouping interval indices by
`interval_start.date()`), not as a single average-rate constraint over the whole horizon
— a real operating/warranty constraint that resets each day, not a monthly budget.

## Consequences

- Solves fast: HiGHS handles a full month of 15-minute intervals as a small-to-medium LP
  in well under a second of solve time (compilation/setup overhead dominates for small
  problems, which is why the golden-case tests — tiny 4-interval problems — take longer
  in wall-clock time per test than the real month-long problem does).
- If a future milestone needs to model a scenario where simultaneous charge/discharge
  *is* rational (e.g. AS deployment energy that behaves differently from capacity
  reservation), the "never both" guarantee no longer holds automatically and would need
  to be revisited — not a concern for M2's capacity-only AS treatment (see
  [0007](0007-as-capacity-only-co-optimization.md)).
