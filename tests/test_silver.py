import datetime as dt

import polars as pl

from ercot_bess.transform.silver import clean_as_prices, clean_load, clean_spp


def _ts(hour: int) -> dt.datetime:
    return dt.datetime(2025, 6, 1, hour, tzinfo=dt.UTC).astimezone()


def test_clean_spp_produces_expected_schema():
    raw = pl.DataFrame(
        {
            "Time": [_ts(0), _ts(1)],
            "Interval Start": [_ts(0), _ts(1)],
            "Interval End": [_ts(1), _ts(2)],
            "Location": ["HB_HOUSTON", "HB_HOUSTON"],
            "Location Type": ["Trading Hub", "Trading Hub"],
            "Market": ["DAY_AHEAD_HOURLY", "DAY_AHEAD_HOURLY"],
            "SPP": [23.0, 24.5],
        }
    )
    clean = clean_spp(raw)
    assert set(clean.columns) == {
        "interval_start",
        "interval_end",
        "location",
        "location_type",
        "market",
        "spp_usd_per_mwh",
        "regime",
    }
    assert clean["spp_usd_per_mwh"].to_list() == [23.0, 24.5]
    assert clean["regime"].to_list() == ["pre_rtcb", "pre_rtcb"]


def test_clean_load_melts_wide_to_long():
    raw = pl.DataFrame(
        {
            "Interval Start": [_ts(0)],
            "Interval End": [_ts(1)],
            "Coast": [10000.0],
            "ERCOT": [43000.0],
        }
    )
    clean = clean_load(raw)
    assert set(clean.columns) == {"interval_start", "interval_end", "zone", "load_mw", "regime"}
    assert clean.height == 2
    zones = dict(zip(clean["zone"].to_list(), clean["load_mw"].to_list(), strict=True))
    assert zones == {"Coast": 10000.0, "ERCOT": 43000.0}


def test_clean_as_prices_melts_and_renames_products():
    raw = pl.DataFrame(
        {
            "Interval Start": [_ts(0)],
            "Interval End": [_ts(1)],
            "RegUp MCPC": [1.5],
            "RegDown MCPC": [0.5],
            "RRS MCPC": [2.0],
            "ECRS MCPC": [0.1],
            "NonSpin MCPC": [0.2],
        }
    )
    clean = clean_as_prices(raw)
    assert clean.height == 5
    products = dict(
        zip(clean["product"].to_list(), clean["mcpc_usd_per_mwh"].to_list(), strict=True)
    )
    assert products == {
        "RegUp": 1.5,
        "RegDown": 0.5,
        "RRS": 2.0,
        "ECRS": 0.1,
        "NonSpin": 0.2,
    }


def test_clean_as_prices_regime_tag_post_rtcb():
    raw = pl.DataFrame(
        {
            "Interval Start": [dt.datetime(2025, 12, 6, tzinfo=dt.UTC).astimezone()],
            "Interval End": [dt.datetime(2025, 12, 6, 1, tzinfo=dt.UTC).astimezone()],
            "RegUp MCPC": [3.0],
        }
    )
    clean = clean_as_prices(raw)
    assert clean["regime"].to_list() == ["post_rtcb"]
