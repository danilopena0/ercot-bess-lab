# 0003: RTC+B regime as a first-class, queryable dimension

**Status:** Accepted (M1)

## Context

ERCOT went live with RTC+B (Real-Time Co-optimization + Batteries) on 2025-12-05. Before
that date, ancillary service capacity is only cleared in the Day-Ahead Market — a battery
has no real-time AS revenue stream, because real-time AS wasn't co-optimized. After that
date, energy and AS are co-optimized every real-time interval. This isn't a cosmetic
market change: it changes which revenue streams are structurally available to a causal
strategy, which changes what a valid strategy formulation even looks like for a given
date. The regime comparison is also the centerpiece of the accompanying analysis (per the
kickoff spec) — the report has to break out strategy performance by regime, not just by
date range.

## Decision

`models/market.py` defines `RTCB_GO_LIVE_DATE` and `regime_for_date(date) -> MarketRegime`
once, and every silver table stamps a `regime` column on every row via this single
function (`transform/silver.py::_with_regime`). No downstream code compares dates against
2025-12-05 directly — it queries or filters on `regime` instead.

This is enforced structurally in the ingestion layer, not just the schema: `ErcotClient.
fetch_rtm_as_mcpc_range` raises if called for a pre-RTC+B date rather than silently
returning empty data, and `ingest/pipeline.py::_ingest_rtm_as_prices` skips pre-RTC+B
dates up front with an explicit log line — treating "there is nothing to fetch" as a
known, intentional state rather than a fetch failure to retry or paper over.

## Consequences

- Adding a new regime-dependent dataset or check later means calling `regime_for_date`
  or filtering on `regime`, not writing a new date comparison — reduces the chance of the
  boundary being forgotten in one code path but not another.
- The regime boundary is hardcoded as a single constant date. If ERCOT revises the RTC+B
  go-live retroactively (unlikely but not impossible for a market design change), it's a
  one-line change in `models/market.py`, not a search-and-replace across the codebase.
- M2/M3 strategy formulations must explicitly account for this: a causal strategy's
  available revenue streams are a function of the regime of the date being simulated, not
  a fixed set decided once for the whole backtest.
