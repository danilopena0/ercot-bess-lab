# ercot-bess-lab

An end-to-end ERCOT battery energy storage system (BESS) dispatch backtester: real market
data in, optimized dispatch strategies out, evaluated the way a trading desk actually
evaluates a battery optimizer — **% of perfect-foresight revenue captured**.

> Status: M2 (perfect foresight) complete. This README will grow with each milestone.

## M2 status

The perfect-foresight LP benchmark (CVXPY/HiGHS) is running against real M1 data — the
revenue ceiling every causal strategy in M3 will be measured against. Three variants,
June 2025, HB_HOUSTON, default 100MW/200MWh battery:

| Variant | Revenue |
|---|---|
| RTM-only (energy arbitrage, 15-min real-time prices) | $371,953 |
| DAM-only (energy arbitrage, hourly day-ahead prices) | $244,166 |
| DAM + AS co-optimized | $517,092 |

The DAM+AS number should be read as an optimistic ceiling, not a realistic estimate —
AS revenue is modeled capacity-only (no deployment energy, no SoC impact from being
called), which is a deliberate simplifying assumption documented in
[ADR 0007](docs/adr/0007-as-capacity-only-co-optimization.md).

**[View the M2 showcase notebook](notebooks/02_m2_perfect_foresight_showcase.ipynb)** —
revenue by variant, the actual dispatch trajectory (charge/discharge/SoC vs. price) for a
sample week and a single zoomed-in day, AS capacity awards by product, and a comparison
against M1's naive arbitrage teaser.

## M1 status

Ingested and DQ-validated a full month (2025-06, deliberately pre-RTC+B) of DAM/RTM
settlement point prices, DAM AS clearing prices, and system load for HB_HOUSTON. All
five silver tables pass data quality checks (no missing intervals, no duplicate
timestamps, correct DST interval counts).

| Dataset | HB_HOUSTON avg | Range |
|---|---|---|
| DAM SPP | $34.62/MWh | $13.26 – $182.12 |
| RTM SPP | $31.94/MWh | -$0.14 – $1250.73 |
| DAM AS (RegUp) | $3.03/MWh | — |
| ERCOT system load | 62,731 MW avg | — |

One real-world data quirk surfaced and handled: ERCOT's RTM SPP report contains
exact-duplicate rows for Load Zone locations (never Trading Hub locations, so
HB_HOUSTON is unaffected), occasionally with penny-level discrepancies between the
two — resolved deterministically via mean aggregation at the silver layer.

**[View the M1 showcase notebook](notebooks/01_m1_data_showcase.ipynb)** — DAM vs RTM
price charts, AS clearing prices, system load, the actual DQ check results, and a rough
(deliberately naive, not the real M2 optimizer) sense of how much arbitrage spread is
in the data.

## What this is

- Pulls real ERCOT Day-Ahead Market (DAM), Real-Time Market (RTM), and Ancillary Services
  (AS) price data via the [`gridstatus`](https://github.com/kmax12/gridstatus) client.
- Runs it through a medallion pipeline (raw → silver → gold) in Polars/DuckDB, stored as
  partitioned Parquet.
- Optimizes battery dispatch with a CVXPY LP/MILP formulation, benchmarked against a
  perfect-foresight upper bound.
- Backtests causal (no-lookahead) strategies — day-ahead commitment and rolling-horizon
  MPC — walk-forward, and reports what fraction of the perfect-foresight ceiling each one
  captures.
- Explicitly analyzes performance across ERCOT's RTC+B market redesign
  (Real-Time Co-optimization + Batteries, live 2025-12-05), since it changes what revenue
  streams a battery can actually access in real time.

## Architecture

```
ingest (gridstatus) → silver (Polars, typed/cleaned) → gold (analysis marts, DuckDB)
                                                              │
                                        ┌─────────────────────┴─────────────────────┐
                                        ▼                                           ▼
                         optimize: perfect foresight LP              optimize + forecast: causal strategies
                         (the revenue ceiling)                       (DA-committed, rolling-horizon MPC)
                                        │                                           │
                                        └─────────────────────┬─────────────────────┘
                                                              ▼
                                              backtest: walk-forward engine,
                                              settlement math, % of perfect revenue
                                                              │
                                                              ▼
                                                    report: HTML report per run
```

## Quickstart

```bash
uv sync
uv run ercot-bess ingest --start 2025-06-01 --end 2025-06-30 --hub HB_HOUSTON
uv run ercot-bess transform --start 2025-06-01 --end 2025-06-30
uv run ercot-bess optimize --start 2025-06-01 --end 2025-06-30 --hub HB_HOUSTON
uv run pytest
```

(Backtest/report commands land in later milestones.)

## Repo layout

```
src/ercot_bess/
├── ingest/     # gridstatus clients, incremental pull, raw parquet cache
├── transform/  # Polars pipelines: raw → silver (clean, typed) → gold (analysis marts)
├── models/     # battery spec, market config, strategy configs (pydantic)
├── optimize/   # LP formulations: perfect foresight, rolling-horizon w/ forecasts
├── forecast/   # baseline price forecasters (persistence, seasonal-naive)
├── backtest/   # walk-forward engine, settlement calc, revenue attribution
├── report/     # report generation, plots, % of perfect revenue tables
└── cli.py
notebooks/      # exploratory/showcase notebooks, one per milestone's worth of proof
```

## Why HB_HOUSTON

Real ERCOT battery fleets concentrate at HB_WEST (wind-congestion negative pricing) and
HB_HOUSTON (CenterPoint transmission congestion, coastal load growth). HB_HOUSTON is used
as the default settlement point here — volatile enough to produce a real arbitrage signal,
while being a recognizable industry benchmark hub. Fully configurable to any hub or node.
See [ADR 0005](docs/adr/0005-default-settlement-point.md) for the full reasoning.

## Docs

- [`docs/adr/`](docs/adr/) — architecture decision records: what was decided, why, and
  what it costs.
- [`docs/milestones/`](docs/milestones/) — a write-up per milestone: what was built, what
  was found along the way, and how it was validated.
