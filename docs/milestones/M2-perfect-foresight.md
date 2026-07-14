# M2 — Perfect Foresight

**Status:** complete, shipped as draft PR (this branch: `worktree-m2-perfect-foresight`).

**Goal (from the kickoff spec):** battery model + LP benchmark running over M1 data,
golden-case tests green, first % numbers.

## What was built

```
src/ercot_bess/optimize/
├── perfect_foresight.py  # the LP: solve_perfect_foresight()
└── data_loading.py        # silver DuckDB views -> plain (timestamps, prices) arrays
```

`solve_perfect_foresight()` takes a realized price series (RTM or DAM), a `BatterySpec`,
and optionally a set of DAM AS clearing price series, and returns the revenue-maximizing
dispatch trajectory — charge/discharge power and state of charge for every interval —
along with a revenue breakdown by stream. See [ADR 0006](../adr/0006-perfect-foresight-lp-formulation.md)
for the LP formulation (why it's a pure LP, not a MILP, and how the daily cycle limit is
enforced per calendar day) and [ADR 0007](../adr/0007-as-capacity-only-co-optimization.md)
for the AS co-optimization assumptions.

`ercot-bess optimize --start ... --end ... --hub ...` runs all three variants the spec
asks for — RTM-only energy arbitrage, a DAM-only participation variant, and a DAM+AS
co-optimized extended variant — over already-ingested silver data.

## Validation

- **Golden-case tests** (`tests/test_perfect_foresight.py`, 6 tests, all hand-derived
  and independently verified before running the solver): basic two-cycle arbitrage with
  no losses ($80 exactly), efficiency losses reducing achievable revenue ($61 exactly,
  with the discharge leg correctly SoC-constrained rather than power-constrained), a
  binding daily cycle limit capping throughput ($20 exactly), a degradation cost large
  enough relative to the price spread to make trading unprofitable (LP correctly finds
  zero trades), AS capacity revenue awarded correctly when energy has no arbitrage value
  ($20 exactly, full power reserved), and an invariant test confirming AS co-optimization
  never produces less revenue than the energy-only baseline for the same prices.
- `uv run ruff check` and `uv run mypy src` clean. (cvxpy ships incomplete type stubs
  that trip up mypy strict mode on `cp.sum`/`cp.multiply`/`Variable.value` — resolved by
  treating the `cvxpy` import as untyped via `follow_imports = "skip"` rather than
  suppressing errors project-wide.)
- **Live run against real M1 data** (June 2025, HB_HOUSTON, 100MW/200MWh default
  battery):

  | Variant | Revenue |
  |---|---|
  | RTM-only (energy arbitrage against 15-min real-time prices) | $371,953 |
  | DAM-only (energy arbitrage against hourly day-ahead prices) | $244,166 |
  | DAM + AS co-optimized | $517,092 (energy $259,283 + AS $282,313 − degradation $24,503) |

  RTM-only being higher than DAM-only makes sense — RTM has substantially more price
  volatility to arbitrage (see the M1 showcase notebook). AS revenue exceeding energy
  revenue in the DAM+AS variant is a direct, expected consequence of the capacity-only
  assumption in ADR 0007: a resource that's never actually called to deliver, and so
  never has its SoC disrupted or faces delivery risk, is cheap for the LP to fully
  commit to AS whenever there's spare power headroom. **This should be read as an
  optimistic ceiling on the AS stream, not a realistic estimate** — flagged explicitly
  so this number isn't mistaken for something more precise than it is.

  Worth comparing against the M1 notebook's naive arbitrage teaser ($391,354, RTM,
  same battery power/energy defaults): the real LP's RTM-only result ($371,953) is
  *lower*, not higher, because the naive M1 calculation assumed frictionless 100%
  round-trip efficiency and zero degradation cost, while the real LP applies the
  `BatterySpec` defaults (86% RTE, $2/MWh degradation) — a physically realistic ceiling
  is necessarily below a frictionless one. This is the expected relationship, not a
  regression.

## Next: M3

Causal (no-lookahead) strategies — DA-committed and rolling-horizon MPC — behind a
walk-forward backtest engine that structurally enforces "strategies may only see data up
to time t." Perfect-foresight revenue computed here becomes the denominator of the
headline "% of perfect revenue captured" metric once M3 has a numerator to put over it.
