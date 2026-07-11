# 0004: Incremental raw cache at daily granularity, routed by data age

**Status:** Accepted (M1)

## Context

Two things became apparent only by actually calling the ERCOT API (not from reading
`gridstatus` docs):

1. ERCOT's public MIS site only keeps a **rolling ~30-day window** of individual report
   documents. `gridstatus`'s date-range methods (`get_spp`, `get_as_prices`, `get_load`)
   query that rolling document list and fail outright for anything older. Historical
   pulls — which this project needs, since M1 deliberately targets a pre-RTC+B month —
   have to go through different, bulk archive endpoints instead
   (`get_dam_spp(year)`, `get_rtm_spp(year)`, `get_hourly_load_post_settlements(year)`).
2. No such bulk archive exists for AS clearing prices in `gridstatus`. The only historical
   source is the 60-day DAM Disclosure report, which is a per-resource award/offer report,
   not a clearing-price report — the clearing price has to be extracted from it (it's
   uniform across resources within an hour, so de-duplicating the per-resource award rows
   down to the MCPC columns recovers it).

This means "fetch the data" isn't one uniform operation across datasets — some datasets
are cheap to re-fetch per year (one API call covers 365 days), others are only available
one delivery day at a time.

## Decision

`RawCache` (`ingest/raw_cache.py`) always caches at daily granularity — one Parquet file
per (dataset, date) — regardless of how the underlying fetch works. `ingest/pipeline.py`
separates datasets into two fetch strategies:

- **Yearly-archive datasets** (`dam_spp`, `rtm_spp`, `load`): if any date in the requested
  range is missing, fetch the whole year once, then slice and write per-day files only
  for the dates actually requested.
- **Daily datasets** (`dam_as_prices`): loop over exactly the missing dates, one API call
  each.

Real-time AS prices get their own path (`_ingest_rtm_as_prices`) that filters to
post-RTC+B dates before ever calling the API — see
[0003](0003-rtcb-regime-as-first-class-dimension.md).

## Consequences

- A single missing date in a yearly-archive dataset re-fetches the entire year, even if
  364 of those days are already cached elsewhere — accepted because the underlying API
  doesn't support fetching a sub-year range from the archive endpoint, and because the
  fetch is one API call regardless of how many days are missing (cheap relative to 30
  separate calls for the daily-dataset case).
- The daily-dataset path (60-day DAM Disclosure) is the slow one — roughly 5-7 seconds
  per delivery day in practice — because it's downloading full per-resource award data
  and discarding everything except the MCPC columns. If AS price ingestion needs to scale
  to multi-year backfills in M4, this is the first place to optimize.
- Because caching is per-day regardless of fetch strategy, re-running `ercot-bess ingest`
  for an overlapping date range never re-fetches anything that's already on disk — this
  was validated in M1 by running the same command twice and confirming zero new file
  writes on the second run.
