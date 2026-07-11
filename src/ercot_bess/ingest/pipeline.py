"""Incremental ingestion orchestration: for a given date range, fetch only what's
missing from the raw cache, and write it before any transformation happens.
"""

import datetime as dt
import logging

import polars as pl

from ercot_bess.ingest.ercot_client import ErcotClient
from ercot_bess.ingest.raw_cache import RawCache
from ercot_bess.models.market import MarketConfig, MarketRegime, regime_for_date

logger = logging.getLogger(__name__)

# Datasets backed by a bulk annual archive: one API call per year covers every
# date in that year, so a single missing date triggers a full-year fetch, then
# each date in the requested range is written out as its own raw-cache file.
_YEARLY_DATASETS = ("dam_spp", "rtm_spp", "load")

# Datasets fetched one delivery day at a time.
_DAILY_DATASETS = ("dam_as_prices",)


def _dates_in_range(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _ingest_yearly_dataset(
    dataset: str,
    config: MarketConfig,
    cache: RawCache,
    client: ErcotClient,
) -> int:
    missing = cache.missing_dates(dataset, config.start_date, config.end_date)
    if not missing:
        logger.info("%s: nothing missing for %s..%s", dataset, config.start_date, config.end_date)
        return 0

    years = sorted({d.year for d in missing})
    written = 0
    for year in years:
        year_dates = [d for d in missing if d.year == year]
        logger.info(
            "%s: fetching full-year archive for %d (%d missing dates)",
            dataset,
            year,
            len(year_dates),
        )
        year_df = _fetch_year(dataset, year, client)
        interval_col = "Interval Start" if "Interval Start" in year_df.columns else "Time"
        for date in year_dates:
            day_df = year_df.filter(pl.col(interval_col).dt.date() == date)
            if day_df.height == 0:
                logger.warning("%s: no rows returned for %s", dataset, date)
                continue
            cache.write(dataset, date, day_df)
            written += 1
    return written


def _fetch_year(dataset: str, year: int, client: ErcotClient) -> pl.DataFrame:
    if dataset == "dam_spp":
        return client.fetch_dam_spp_year(year)
    if dataset == "rtm_spp":
        return client.fetch_rtm_spp_year(year)
    if dataset == "load":
        return client.fetch_load_year(year)
    raise ValueError(f"Unknown yearly dataset: {dataset}")


def _ingest_daily_dataset(
    dataset: str,
    config: MarketConfig,
    cache: RawCache,
    client: ErcotClient,
) -> int:
    missing = cache.missing_dates(dataset, config.start_date, config.end_date)
    written = 0
    for date in missing:
        logger.info("%s: fetching %s", dataset, date)
        df = client.fetch_dam_as_mcpc_day(date)
        if df.height == 0:
            logger.warning("%s: no rows returned for %s", dataset, date)
            continue
        cache.write(dataset, date, df)
        written += 1
    return written


def _ingest_rtm_as_prices(
    config: MarketConfig,
    cache: RawCache,
    client: ErcotClient,
) -> int:
    dataset = "rtm_as_prices"
    missing = cache.missing_dates(dataset, config.start_date, config.end_date)
    post_rtcb_missing = [d for d in missing if regime_for_date(d) == MarketRegime.POST_RTCB]
    skipped = len(missing) - len(post_rtcb_missing)
    if skipped:
        logger.info(
            "%s: skipping %d pre-RTC+B date(s) — real-time AS wasn't co-optimized "
            "before 2025-12-05, so there is no clearing price to fetch",
            dataset,
            skipped,
        )
    written = 0
    for date in post_rtcb_missing:
        logger.info("%s: fetching %s", dataset, date)
        df = client.fetch_rtm_as_mcpc_range(date, date)
        if df.height == 0:
            logger.warning("%s: no rows returned for %s", dataset, date)
            continue
        cache.write(dataset, date, df)
        written += 1
    return written


def run_ingestion(config: MarketConfig, cache: RawCache | None = None) -> dict[str, int]:
    """Run incremental ingestion for every dataset over config's date range.

    Returns a dict of dataset name -> number of new raw files written.
    """
    cache = cache or RawCache()
    client = ErcotClient()

    results: dict[str, int] = {}
    for dataset in _YEARLY_DATASETS:
        results[dataset] = _ingest_yearly_dataset(dataset, config, cache, client)
    for dataset in _DAILY_DATASETS:
        results[dataset] = _ingest_daily_dataset(dataset, config, cache, client)
    results["rtm_as_prices"] = _ingest_rtm_as_prices(config, cache, client)

    return results
