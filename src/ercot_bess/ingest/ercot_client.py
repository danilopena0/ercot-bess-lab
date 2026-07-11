"""Thin wrapper around gridstatus.Ercot() that picks the right underlying report
for the age of the data being requested.

ERCOT's public MIS site only keeps a *rolling* window of individual daily report
documents (empirically, on the order of a month) before they expire. Beyond that
window, historical data has to come from a different, bulk archive report:

- DAM/RTM settlement point prices: `get_spp(...)` only reaches the rolling window;
  `get_dam_spp(year)` / `get_rtm_spp(year)` pull the full-year historical archive
  and work back to 2011.
- System load: `get_load(...)` only reaches the rolling window;
  `get_hourly_load_post_settlements(year)` pulls ERCOT's historical load archive.
- DAM ancillary service clearing prices: `get_as_prices(...)` / `get_mcpc_dam(...)`
  only reach the rolling window. There is no bulk annual archive for AS clearing
  prices in gridstatus, but the 60-day DAM Disclosure report
  (`get_60_day_dam_disclosure`) includes per-resource AS awards *and* the market
  clearing price for capacity (MCPC) for each AS product, which is uniform across
  resources within an hour — so it can be de-duplicated down to one clearing-price
  row per hour. This is only available 60 days after the fact, which is exactly
  the historical case we need it for.
- Real-time AS clearing prices (`get_mcpc_real_time_15_min`) are only meaningful
  post-RTC+B (2025-12-05) since real-time AS wasn't co-optimized before that. This
  wrapper does not fetch them for pre-RTC+B dates.

This module always returns Polars DataFrames — gridstatus returns pandas.
"""

import datetime as dt

import gridstatus
import polars as pl

from ercot_bess.models.market import MarketRegime, regime_for_date


class ErcotClient:
    def __init__(self) -> None:
        self._client = gridstatus.Ercot()

    def fetch_dam_spp_year(self, year: int) -> pl.DataFrame:
        """DAM settlement point prices for every hub/load zone, for a full year."""
        df = self._client.get_dam_spp(year)
        return pl.from_pandas(df)

    def fetch_rtm_spp_year(self, year: int) -> pl.DataFrame:
        """RTM (15-min) settlement point prices for every hub/load zone, for a full year."""
        df = self._client.get_rtm_spp(year)
        return pl.from_pandas(df)

    def fetch_load_year(self, year: int) -> pl.DataFrame:
        """Hourly system-wide and weather-zone load, for a full year."""
        df = self._client.get_hourly_load_post_settlements(str(year))
        return pl.from_pandas(df)

    def fetch_dam_as_mcpc_day(self, date: dt.date) -> pl.DataFrame:
        """DAM ancillary service clearing prices (MCPC) for a single delivery day.

        Sourced from the 60-day DAM Disclosure report's `dam_load_resource` table,
        which carries the market clearing price for capacity alongside per-resource
        awards. MCPC is identical across resources within an hour, so we drop the
        award columns and de-duplicate down to one row per hour.
        """
        disclosure = self._client.get_60_day_dam_disclosure(date.isoformat())
        load_resource = disclosure["dam_load_resource"]
        mcpc_cols = [c for c in load_resource.columns if "MCPC" in c]
        subset = load_resource[["Interval Start", "Interval End", *mcpc_cols]]
        subset = subset.dropna(how="all", subset=mcpc_cols).drop_duplicates(
            subset=["Interval Start"]
        )
        return pl.from_pandas(subset)

    def fetch_rtm_as_mcpc_range(self, start: dt.date, end: dt.date) -> pl.DataFrame:
        """Real-time (15-min) AS clearing prices. Only fetched for post-RTC+B dates."""
        if regime_for_date(start) != MarketRegime.POST_RTCB:
            raise ValueError(
                f"Real-time AS clearing prices requested for {start}, which is "
                "pre-RTC+B (before 2025-12-05); real-time AS was not co-optimized "
                "before that date, so there is nothing meaningful to fetch."
            )
        df = self._client.get_mcpc_real_time_15_min(start.isoformat(), end=end.isoformat())
        return pl.from_pandas(df)
