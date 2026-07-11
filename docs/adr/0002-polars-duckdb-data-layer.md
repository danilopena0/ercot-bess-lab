# 0002: Polars + DuckDB for the local data layer

**Status:** Accepted (M1) — mandated by the project kickoff spec; this ADR records the
reasoning, not the choice itself.

## Context

The pipeline runs on a laptop, not a cluster (SPEC.md is explicit: "no Airflow — keep it
runnable on a laptop with one command"). It needs a dataframe library for the raw→silver
transforms and a query layer for downstream analysis (DQ checks, the optimizer, the
backtester, the report) — all against a dataset that's small by data-engineering standards
(a few years of interval timeseries at one hub is low millions of rows) but needs to be
fast to iterate on repeatedly during development.

## Decision

- **Polars** for all dataframe transforms (`transform/silver.py`, `transform/dq.py`).
  Chosen over pandas for its stricter typing (no silent object-dtype columns), lazy/eager
  execution model, and speed on the group-by/melt-heavy operations the silver layer does
  (e.g. de-duplicating RTM SPP rows, melting wide AS/load columns to long).
- **DuckDB** as the query layer, reading Parquet directly with `hive_partitioning=true`
  rather than requiring a separate load/ETL step into a database file. No server process,
  no separate infrastructure to run.
- `gridstatus` itself returns pandas DataFrames (it's built on pandas), so the boundary
  is explicit: `ErcotClient` converts pandas → Polars immediately via `pl.from_pandas()`
  at the ingestion boundary, and pandas never appears past that point in the codebase.

## Consequences

- One extra conversion step at the `gridstatus` boundary, but it keeps "pandas is a
  third-party library's return type" cleanly separated from "Polars is this project's
  dataframe library."
- DuckDB views over Parquet mean there's no separate "load the warehouse" step to forget
  to re-run — but it also means query performance depends on Parquet file layout
  (partition pruning), which is why silver is partitioned by date (ADR 0001).
