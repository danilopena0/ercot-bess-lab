"""Raw -> silver: clean, explicitly-typed, long-format Polars pipelines.

Every silver table shares the same interval-timeseries shape (interval_start,
interval_end, ..., value, regime) so downstream code (DQ checks, gold marts,
the optimizer) doesn't need dataset-specific branching. `regime` is stamped on
every row here rather than computed downstream, so a query can never forget to
account for the pre/post-RTC+B boundary.

Partitioned by dataset then delivery date (Hive-style `date=YYYY-MM-DD` dirs),
one file per day, mirroring the raw cache layout — a config change to Iceberg
later only needs to swap the write/read calls, not the partitioning scheme.
"""

import datetime as dt
from pathlib import Path

import polars as pl

from ercot_bess.ingest.raw_cache import RawCache
from ercot_bess.models.market import regime_for_date

DEFAULT_SILVER_ROOT = Path("data/silver")

AS_PRODUCT_COLUMNS = {
    "RegUp MCPC": "RegUp",
    "RegDown MCPC": "RegDown",
    "RRS MCPC": "RRS",
    "ECRS MCPC": "ECRS",
    "NonSpin MCPC": "NonSpin",
}

LOAD_ZONE_COLUMNS = [
    "Coast",
    "East",
    "Far West",
    "North",
    "North Central",
    "South",
    "South Central",
    "West",
    "ERCOT",
]


def _with_regime(df: pl.DataFrame, ts_col: str = "interval_start") -> pl.DataFrame:
    regime_expr = pl.col(ts_col).dt.date().map_elements(
        lambda d: regime_for_date(d).value, return_dtype=pl.Utf8
    )
    return df.with_columns(regime_expr.alias("regime"))


def clean_spp(raw: pl.DataFrame) -> pl.DataFrame:
    """Silver schema for DAM/RTM settlement point prices.

    ERCOT's RTM SPP report carries occasional exact-duplicate rows for Load Zone
    locations (never observed for Trading Hub locations), sometimes with a
    penny-level SPP discrepancy between the two (e.g. 30.54 vs 30.53) — consistent
    with the settlement point price being a load-weighted average of underlying
    resource nodes that got reported at two slightly different vintages. Rather
    than arbitrarily keeping one row, duplicates are collapsed with a mean, which
    is deterministic and immaterial at this magnitude.
    """
    df = raw.select(
        pl.col("Interval Start").alias("interval_start"),
        pl.col("Interval End").alias("interval_end"),
        pl.col("Location").cast(pl.Utf8).alias("location"),
        pl.col("Location Type").cast(pl.Utf8).alias("location_type"),
        pl.col("Market").cast(pl.Utf8).alias("market"),
        pl.col("SPP").cast(pl.Float64).alias("spp_usd_per_mwh"),
    )
    df = df.group_by(
        ["interval_start", "interval_end", "location", "location_type", "market"],
        maintain_order=True,
    ).agg(pl.col("spp_usd_per_mwh").mean())
    return _with_regime(df)


def clean_load(raw: pl.DataFrame) -> pl.DataFrame:
    """Silver schema for hourly load: melted from wide (one column per zone) to long."""
    present_zones = [c for c in LOAD_ZONE_COLUMNS if c in raw.columns]
    df = raw.select(
        pl.col("Interval Start").alias("interval_start"),
        pl.col("Interval End").alias("interval_end"),
        *[pl.col(c).cast(pl.Float64) for c in present_zones],
    ).unpivot(
        index=["interval_start", "interval_end"],
        on=present_zones,
        variable_name="zone",
        value_name="load_mw",
    )
    return _with_regime(df)


def clean_as_prices(raw: pl.DataFrame) -> pl.DataFrame:
    """Silver schema for AS clearing prices (DAM or RT): melted from wide MCPC
    columns to long, one row per (interval, product)."""
    present = [c for c in AS_PRODUCT_COLUMNS if c in raw.columns]
    df = raw.select(
        pl.col("Interval Start").alias("interval_start"),
        pl.col("Interval End").alias("interval_end"),
        *[pl.col(c).cast(pl.Float64) for c in present],
    ).unpivot(
        index=["interval_start", "interval_end"],
        on=present,
        variable_name="product",
        value_name="mcpc_usd_per_mwh",
    ).with_columns(pl.col("product").replace(AS_PRODUCT_COLUMNS))
    return _with_regime(df)


_CLEANERS = {
    "dam_spp": clean_spp,
    "rtm_spp": clean_spp,
    "load": clean_load,
    "dam_as_prices": clean_as_prices,
    "rtm_as_prices": clean_as_prices,
}


def build_silver_table(
    dataset: str,
    start: dt.date,
    end: dt.date,
    raw_cache: RawCache | None = None,
    silver_root: Path = DEFAULT_SILVER_ROOT,
) -> pl.DataFrame:
    """Read raw parquet for [start, end], clean it, and write one silver parquet
    file per day. Returns the full cleaned range as a single DataFrame.
    """
    raw_cache = raw_cache or RawCache()
    cleaner = _CLEANERS[dataset]

    raw = raw_cache.read_range(dataset, start, end)
    if raw.height == 0:
        return pl.DataFrame()

    clean = cleaner(raw)

    out_dir = silver_root / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = clean.with_columns(pl.col("interval_start").dt.date().alias("_date"))
    for (date,), day_df in dated.group_by(["_date"], maintain_order=True):
        day_dir = out_dir / f"date={date.isoformat()}"
        day_dir.mkdir(parents=True, exist_ok=True)
        day_df.drop("_date").write_parquet(day_dir / "part-0.parquet")

    return clean
