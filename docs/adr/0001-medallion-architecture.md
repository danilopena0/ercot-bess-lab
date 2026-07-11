# 0001: Medallion architecture with Iceberg-ready partitioning

**Status:** Accepted (M1)

## Context

The pipeline needs a storage layout that survives beyond a single script run: raw API
responses have to be cached before any cleaning happens (so a bug in the cleaning logic
never requires re-hitting the ERCOT API), cleaned data needs to be queryable without
re-running Python, and the project is explicitly expected to outgrow a single laptop
eventually — SPEC.md calls for table schemas designed so a later migration to Iceberg is
a config change, not a rewrite.

## Decision

Three layers on local Parquet:

- `data/raw/<dataset>/<date>.parquet` — exactly what came back from `gridstatus`,
  untouched, one file per (dataset, date).
- `data/silver/<dataset>/date=<date>/part-0.parquet` — cleaned, explicitly typed,
  long-format, Hive-style partitioned by date.
- `data/gold/` — reserved for M2+ analysis marts (e.g. a battery-revenue mart joining
  prices with optimizer output). Not built in M1.

Every silver table shares the same shape (`interval_start`, `interval_end`, ..., a value
column, `regime`) regardless of dataset, so DQ checks and downstream queries don't need
per-dataset branching.

Silver is exposed via DuckDB **views** over the Parquet files (`transform/duckdb_store.py`),
not materialized tables — the files on disk stay the single source of truth, so re-running
the silver transform is immediately visible without a separate load step.

## Consequences

- Iceberg migration later is a matter of swapping the write/read calls in `silver.py` and
  `duckdb_store.py` for Iceberg equivalents; the partitioning scheme (dataset, then date)
  carries over unchanged.
- Raw and silver are gitignored (`data/**` in `.gitignore`) — the data lake is regenerated
  by `ercot-bess ingest`/`transform`, not checked into source control. Only `.gitkeep`
  placeholders are committed.
- Cost: an extra disk-write pass between raw and silver on every run, and slightly more
  ceremony than "just query the raw files directly" — accepted because raw data is known
  to have real defects (see [0004](0004-incremental-raw-cache-and-report-routing.md) and
  the M1 write-up) that must be resolved once, deterministically, not on every query.
