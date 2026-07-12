"""Adapters from the silver DuckDB views to the plain (timestamps, prices) sequences
`solve_perfect_foresight` expects. Kept separate from the LP itself so the optimizer
core has no knowledge of DuckDB/silver schemas — it only ever sees arrays.
"""

import datetime as dt

import duckdb
import polars as pl

from ercot_bess.optimize.perfect_foresight import DOWN_AS_PRODUCTS, UP_AS_PRODUCTS


def load_spp_series(
    con: duckdb.DuckDBPyConnection,
    table: str,
    hub: str,
    start_date: dt.date,
    end_date: dt.date,
) -> tuple[list[dt.datetime], list[float]]:
    """Settlement point price series for one hub, ordered by interval_start."""
    df = con.execute(
        f"""
        SELECT interval_start, spp_usd_per_mwh
        FROM {table}
        WHERE location = ?
          AND interval_start >= ?
          AND interval_start < ?
        ORDER BY interval_start
        """,
        [hub, start_date, end_date + dt.timedelta(days=1)],
    ).pl()
    return df.get_column("interval_start").to_list(), df.get_column("spp_usd_per_mwh").to_list()


def load_dam_as_price_series(
    con: duckdb.DuckDBPyConnection,
    interval_start: list[dt.datetime],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, list[float]]:
    """DAM AS clearing prices by product, reindexed onto `interval_start` (which
    should be the DAM energy price timestamps — AS clears hourly, same as DAM).
    Raises if any requested timestamp is missing a clearing price for a product,
    rather than silently zero-filling a gap.
    """
    df = con.execute(
        """
        SELECT interval_start, product, mcpc_usd_per_mwh
        FROM silver_dam_as_prices
        WHERE interval_start >= ? AND interval_start < ?
        """,
        [start_date, end_date + dt.timedelta(days=1)],
    ).pl()

    known_products = set(UP_AS_PRODUCTS + DOWN_AS_PRODUCTS)
    products = sorted(set(df.get_column("product").to_list()) & known_products)
    result: dict[str, list[float]] = {}
    for product in products:
        sub = df.filter(pl.col("product") == product)
        price_by_ts = dict(
            zip(
                sub.get_column("interval_start").to_list(),
                sub.get_column("mcpc_usd_per_mwh").to_list(),
                strict=True,
            )
        )
        missing = [ts for ts in interval_start if ts not in price_by_ts]
        if missing:
            raise ValueError(
                f"AS product {product!r} is missing clearing prices for {len(missing)} interval(s)"
            )
        result[product] = [price_by_ts[ts] for ts in interval_start]
    return result
