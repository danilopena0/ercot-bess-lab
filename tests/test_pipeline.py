import datetime as dt
from unittest.mock import MagicMock

import polars as pl

from ercot_bess.ingest.pipeline import (
    _ingest_daily_dataset,
    _ingest_rtm_as_prices,
    _ingest_yearly_dataset,
)
from ercot_bess.ingest.raw_cache import RawCache
from ercot_bess.models.market import MarketConfig


def _year_df(year: int) -> pl.DataFrame:
    ts = pl.datetime_range(
        dt.datetime(year, 1, 1), dt.datetime(year + 1, 1, 1), interval="1d", eager=True
    )
    return pl.DataFrame({"Interval Start": ts, "value": list(range(len(ts)))})


def test_yearly_dataset_fetches_year_once_regardless_of_missing_day_count(tmp_path):
    cache = RawCache(root=tmp_path)
    client = MagicMock()
    client.fetch_dam_spp_year.return_value = _year_df(2025)

    config = MarketConfig(start_date=dt.date(2025, 6, 1), end_date=dt.date(2025, 6, 5))
    written = _ingest_yearly_dataset("dam_spp", config, cache, client)

    assert written == 5
    client.fetch_dam_spp_year.assert_called_once_with(2025)
    for i in range(5):
        assert cache.has_date("dam_spp", dt.date(2025, 6, 1 + i))


def test_yearly_dataset_skips_fetch_when_nothing_missing(tmp_path):
    cache = RawCache(root=tmp_path)
    for i in range(5):
        cache.write("dam_spp", dt.date(2025, 6, 1 + i), pl.DataFrame({"a": [1]}))

    client = MagicMock()
    config = MarketConfig(start_date=dt.date(2025, 6, 1), end_date=dt.date(2025, 6, 5))
    written = _ingest_yearly_dataset("dam_spp", config, cache, client)

    assert written == 0
    client.fetch_dam_spp_year.assert_not_called()


def test_daily_dataset_fetches_only_missing_dates(tmp_path):
    cache = RawCache(root=tmp_path)
    cache.write("dam_as_prices", dt.date(2025, 6, 1), pl.DataFrame({"a": [1]}))

    client = MagicMock()
    client.fetch_dam_as_mcpc_day.return_value = pl.DataFrame({"a": [1]})

    config = MarketConfig(start_date=dt.date(2025, 6, 1), end_date=dt.date(2025, 6, 3))
    written = _ingest_daily_dataset("dam_as_prices", config, cache, client)

    assert written == 2
    assert client.fetch_dam_as_mcpc_day.call_count == 2
    called_dates = {c.args[0] for c in client.fetch_dam_as_mcpc_day.call_args_list}
    assert called_dates == {dt.date(2025, 6, 2), dt.date(2025, 6, 3)}


def test_rtm_as_prices_skips_pre_rtcb_dates(tmp_path):
    cache = RawCache(root=tmp_path)
    client = MagicMock()
    client.fetch_rtm_as_mcpc_range.return_value = pl.DataFrame({"a": [1]})

    # spans the RTC+B boundary: 2025-12-04 pre, 2025-12-05/06 post
    config = MarketConfig(start_date=dt.date(2025, 12, 4), end_date=dt.date(2025, 12, 6))
    written = _ingest_rtm_as_prices(config, cache, client)

    assert written == 2
    called_dates = {c.args[0] for c in client.fetch_rtm_as_mcpc_range.call_args_list}
    assert called_dates == {dt.date(2025, 12, 5), dt.date(2025, 12, 6)}
    assert not cache.has_date("rtm_as_prices", dt.date(2025, 12, 4))
