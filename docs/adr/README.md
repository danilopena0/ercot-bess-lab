# Architecture Decision Records

Each ADR captures one decision, the context that forced it, and what it costs — written
at the time the decision was made, not reconstructed later. They're numbered and
immutable: if a decision changes, a new ADR supersedes the old one rather than editing it
in place.

| # | Decision | Status |
|---|---|---|
| [0001](0001-medallion-architecture.md) | Medallion architecture (raw/silver/gold), Iceberg-ready partitioning | Accepted |
| [0002](0002-polars-duckdb-data-layer.md) | Polars + DuckDB for the local data layer | Accepted |
| [0003](0003-rtcb-regime-as-first-class-dimension.md) | RTC+B regime as a first-class, queryable dimension | Accepted |
| [0004](0004-incremental-raw-cache-and-report-routing.md) | Incremental raw cache at daily granularity, routed by data age | Accepted |
| [0005](0005-default-settlement-point.md) | HB_HOUSTON as the default settlement point | Accepted |
| [0006](0006-perfect-foresight-lp-formulation.md) | Perfect-foresight dispatch as an LP, not a MILP | Accepted |
| [0007](0007-as-capacity-only-co-optimization.md) | AS co-optimization is capacity-only, no deployment energy | Accepted |
