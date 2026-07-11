"""Registers silver Parquet partitions as DuckDB views.

Views (not materialized tables) so `data/silver/**` on disk stays the single
source of truth — re-running the silver transform is immediately reflected
without a separate load step.
"""

from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/ercot.duckdb")
DEFAULT_SILVER_ROOT = Path("data/silver")

SILVER_DATASETS = ("dam_spp", "rtm_spp", "load", "dam_as_prices", "rtm_as_prices")


def register_silver_views(
    db_path: Path = DEFAULT_DB_PATH,
    silver_root: Path = DEFAULT_SILVER_ROOT,
) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    for dataset in SILVER_DATASETS:
        glob = silver_root / dataset / "**" / "*.parquet"
        if not any((silver_root / dataset).glob("**/*.parquet")):
            continue
        con.execute(
            f"CREATE OR REPLACE VIEW silver_{dataset} AS "
            f"SELECT * FROM read_parquet('{glob.as_posix()}', hive_partitioning=true)"
        )
    return con
