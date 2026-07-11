import datetime as dt

import polars as pl

from ercot_bess.ingest.raw_cache import RawCache


def test_missing_dates_all_missing_when_empty(tmp_path):
    cache = RawCache(root=tmp_path)
    missing = cache.missing_dates("dam_spp", dt.date(2025, 6, 1), dt.date(2025, 6, 3))
    assert missing == [dt.date(2025, 6, 1), dt.date(2025, 6, 2), dt.date(2025, 6, 3)]


def test_write_then_missing_dates_excludes_written(tmp_path):
    cache = RawCache(root=tmp_path)
    df = pl.DataFrame({"a": [1, 2, 3]})
    cache.write("dam_spp", dt.date(2025, 6, 2), df)

    missing = cache.missing_dates("dam_spp", dt.date(2025, 6, 1), dt.date(2025, 6, 3))
    assert missing == [dt.date(2025, 6, 1), dt.date(2025, 6, 3)]


def test_has_date(tmp_path):
    cache = RawCache(root=tmp_path)
    assert not cache.has_date("dam_spp", dt.date(2025, 6, 2))
    cache.write("dam_spp", dt.date(2025, 6, 2), pl.DataFrame({"a": [1]}))
    assert cache.has_date("dam_spp", dt.date(2025, 6, 2))


def test_read_range_concatenates_written_days(tmp_path):
    cache = RawCache(root=tmp_path)
    cache.write("dam_spp", dt.date(2025, 6, 1), pl.DataFrame({"a": [1, 2]}))
    cache.write("dam_spp", dt.date(2025, 6, 2), pl.DataFrame({"a": [3]}))

    combined = cache.read_range("dam_spp", dt.date(2025, 6, 1), dt.date(2025, 6, 3))
    assert combined.height == 3


def test_read_range_empty_when_nothing_cached(tmp_path):
    cache = RawCache(root=tmp_path)
    combined = cache.read_range("dam_spp", dt.date(2025, 6, 1), dt.date(2025, 6, 3))
    assert combined.is_empty()


def test_datasets_are_isolated(tmp_path):
    cache = RawCache(root=tmp_path)
    cache.write("dam_spp", dt.date(2025, 6, 1), pl.DataFrame({"a": [1]}))
    assert not cache.has_date("rtm_spp", dt.date(2025, 6, 1))
