# M1 — Skeleton + Ingestion

**Status:** complete, shipped as draft PR [#1](https://github.com/danilopena0/ercot-bess-lab/pull/1)
on branch `worktree-m1-skeleton-ingestion`.

**Goal (from the kickoff spec):** repo scaffold, `gridstatus` ingestion for one month of
DAM/RTM/AS data at one hub, silver tables in DuckDB, DQ checks passing.

## Decisions made before writing code

Three things weren't specified up front and were decided with the user before M1 started:

| Decision | Choice | Why |
|---|---|---|
| Default settlement point | `HB_HOUSTON` | Real ERCOT battery fleets concentrate at HB_WEST (largest, wind-congestion arbitrage) and HB_HOUSTON (second largest, CenterPoint transmission congestion). HB_HOUSTON was picked over HB_WEST as the default for being a recognizable industry benchmark hub while less noisy for early tests/debugging. |
| M1 data month | 2025-06 (pre-RTC+B) | Deliberately chosen *before* RTC+B (2025-12-05) so M1 sanity-checks the old-regime schema and data shape before M4 extends to full history spanning both regimes. |
| Delivery cadence | Draft PR + pause after each milestone | Rather than one PR at the end, to match the SPEC.md instruction to confirm at each checkpoint. |

## What was built

```
src/ercot_bess/
├── models/
│   ├── battery.py     # BatterySpec: 100MW/200MWh/86% RTE/1.5 cycles/day/$2/MWh defaults
│   └── market.py       # MarketConfig, regime_for_date() — RTC+B boundary as a first-class dimension
├── ingest/
│   ├── ercot_client.py # wraps gridstatus.Ercot(), routes each dataset to the right report
│   ├── raw_cache.py    # one parquet file per (dataset, date) — makes ingestion incremental
│   └── pipeline.py     # orchestrates incremental fetch across all 5 datasets
├── transform/
│   ├── silver.py        # raw -> clean/typed/long-format Parquet, partitioned by dataset/date
│   ├── dq.py             # missing intervals, duplicate timestamps, DST transition-day checks
│   └── duckdb_store.py   # registers silver Parquet as DuckDB views
└── cli.py               # `ercot-bess ingest|transform|dq`
```

Datasets pulled: DAM settlement point prices, RTM settlement point prices, DAM ancillary
service clearing prices (RegUp/RegDown/RRS/ECRS/NonSpin), system load. Real-time AS
clearing prices are wired but intentionally not fetched for pre-RTC+B dates (see below).

## Real-world findings

These weren't known going in — they came from actually calling the ERCOT APIs, not from
reading docs:

1. **ERCOT's public MIS only keeps a rolling ~30-day window of individual report
   documents.** `get_spp`, `get_as_prices`, and `get_load` (gridstatus's date-range
   methods) all failed for June 2025 dates once "today" was more than ~30-45 days past
   them. Fix: route historical pulls to the bulk annual archive endpoints instead
   (`get_dam_spp(year)`, `get_rtm_spp(year)`, `get_hourly_load_post_settlements(year)`).
   For AS clearing prices, no annual archive exists in `gridstatus` at all — historical
   DAM AS MCPCs are sourced from the 60-day DAM Disclosure report
   (`get_60_day_dam_disclosure(date)['dam_load_resource']`), de-duplicated down to one
   clearing-price row per hour.

2. **RTM SPP has exact-duplicate rows for Load Zone locations** in ERCOT's raw report
   (Trading Hub locations — including the default HB_HOUSTON — are unaffected).
   Occasionally the two duplicate rows disagree at the penny level (e.g. $30.54 vs
   $30.53), consistent with the load zone price being a load-weighted average of
   underlying resource nodes reported at two slightly different vintages. Resolved
   deterministically via mean aggregation in `clean_spp`, rather than arbitrarily
   keeping one row.

3. **DST checks must be scoped to the queried date range, not the whole year.** The
   first version of `run_dq_checks` checked both DST transition days for every year
   touched by the query, which produced false positives ("expected 23, found 0") on
   short date ranges that didn't include March or November at all. Fixed by only
   checking a transition day if it actually falls within `[start, end)`.

4. **Real-time AS clearing prices are structurally unavailable pre-RTC+B**, not just
   empty — real-time AS wasn't co-optimized before 2025-12-05, so there's no clearing
   price to fetch. `ErcotClient.fetch_rtm_as_mcpc_range` raises rather than silently
   returning empty data if called for a pre-RTC+B date, and the ingestion pipeline skips
   those dates up front with an explicit log line rather than treating it as a fetch
   failure.

## Validation

- `uv run pytest`: 30 tests passing — `BatterySpec`/`MarketConfig` validation, `RawCache`
  incremental missing-date logic, DQ checks (including synthetic DST edge cases), silver
  cleaning transforms, and pipeline orchestration against a mocked `ErcotClient`.
- `uv run ruff check` and `uv run mypy src`: clean.
- Live end-to-end run against the real ERCOT API: `ercot-bess ingest --start 2025-06-01
  --end 2025-06-30 --hub HB_HOUSTON` → `ercot-bess transform --start ... --end ...` →
  `ercot-bess dq --start ... --end ...`. All five silver tables (`dam_spp`, `rtm_spp`,
  `load`, `dam_as_prices`; `rtm_as_prices` empty as expected pre-RTC+B) came back CLEAN.

  | Dataset | HB_HOUSTON avg | Range |
  |---|---|---|
  | DAM SPP | $34.62/MWh | $13.26 – $182.12 |
  | RTM SPP | $31.94/MWh | -$0.14 – $1250.73 |
  | DAM AS (RegUp) | $3.03/MWh | — |
  | ERCOT system load | 62,731 MW avg | — |

  These are in line with real June 2025 ERCOT summer conditions (real-time volatility,
  occasional negative pricing, AS prices in the low single digits).

## What's next (M2)

Battery model is already in place (`models/battery.py`). M2 builds the perfect-foresight
LP benchmark (CVXPY/HiGHS) over this ingested data, with golden-case tests on small
hand-solvable dispatch problems, producing the first "% of perfect revenue" numbers.
