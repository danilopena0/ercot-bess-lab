# 0007: AS co-optimization is capacity-only, no deployment energy

**Status:** Accepted (M2)

## Context

SPEC.md asks for "an extended variant that co-optimizes energy + AS capacity awards
using AS clearing prices (document the simplifying assumptions clearly — e.g., no
deployment energy for AS, price-taker)." Real AS provision has two revenue/cost
components: a **capacity payment** for being awarded and available (the MCPC clearing
price times MW awarded), and **deployment** — actually being called to inject or absorb
energy when the grid operator needs it, which draws down or charges the battery's SoC
unpredictably and competes directly with planned energy arbitrage.

Modeling deployment properly would require either a stochastic/scenario-based
formulation (deployment isn't known with certainty even under "perfect foresight" of
prices, since AS calls depend on real-time system conditions) or historical AS
deployment factor data layered on top of clearing prices — meaningfully more complexity
than a benchmark LP needs to establish a first revenue ceiling.

## Decision

Model AS revenue as capacity-only: `as_revenue = sum(award_mw * mcpc_price * dt)` for
each product, with no corresponding energy deployment, no SoC impact from being called,
and no separate deployment payment/penalty. The battery is a **price-taker** in both the
energy and AS markets (its bids/offers never move the clearing price — reasonable for a
100–200MW asset in an ERCOT-scale market).

The only interaction AS awards have with the rest of the model is **power headroom**:
awarding capacity to an "up" product (RegUp, RRS, ECRS, NonSpin — called to increase
output) competes with `discharge` for the same MW envelope; awarding RegDown ("down,"
called to decrease output / increase consumption) competes with `charge`. See
`UP_AS_PRODUCTS` / `DOWN_AS_PRODUCTS` in `optimize/perfect_foresight.py`.

## Consequences

- **This materially overstates AS revenue relative to what a real resource would earn.**
  In the M2 validation run (June 2025, HB_HOUSTON, 100MW/200MWh), AS capacity revenue
  ($282,313) was larger than energy arbitrage revenue itself ($259,283) in the DAM+AS
  variant — a battery that's never actually called to deliver, and therefore never has
  its SoC disrupted or faces the risk of being unable to deliver, is being paid as if
  that risk didn't exist. Any comparison using the DAM+AS number should be read as an
  optimistic ceiling on the AS revenue stream specifically, not a realistic estimate.
- Because there's no SoC or deployment interaction, awarding AS capacity is very cheap
  for the LP to do whenever there's spare power headroom — expect AS awards to be at or
  near full available headroom whenever `MCPC > 0` and that headroom isn't more
  valuable for energy arbitrage in that interval.
- A future milestone modeling deployment (e.g. using ERCOT's AS deployment factor
  reports, which `gridstatus` also exposes) would need to revisit both this ADR and
  [0006](0006-perfect-foresight-lp-formulation.md)'s "never simultaneous charge/discharge"
  argument, since deployment could make holding both a charge/discharge position and an
  AS award simultaneously rational in ways pure arbitrage never is.
