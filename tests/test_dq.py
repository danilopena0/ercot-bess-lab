import datetime as dt

import polars as pl

from ercot_bess.transform.dq import (
    check_dst_days,
    check_duplicate_timestamps,
    check_missing_intervals,
)


def _hourly_range(start: dt.datetime, end: dt.datetime) -> pl.Series:
    return pl.datetime_range(
        start, end, interval="1h", time_zone="US/Central", closed="left", eager=True
    )


def test_check_duplicate_timestamps_detects_dupe():
    ts = _hourly_range(dt.datetime(2025, 6, 1), dt.datetime(2025, 6, 2))
    df = pl.DataFrame({"interval_start": list(ts) + [ts[0]]})
    dupes = check_duplicate_timestamps(df, "interval_start")
    assert dupes == [ts[0]]


def test_check_duplicate_timestamps_none_when_clean():
    ts = _hourly_range(dt.datetime(2025, 6, 1), dt.datetime(2025, 6, 2))
    df = pl.DataFrame({"interval_start": ts})
    assert check_duplicate_timestamps(df, "interval_start") == []


def test_check_missing_intervals_detects_gap():
    ts = _hourly_range(dt.datetime(2025, 6, 1), dt.datetime(2025, 6, 2))
    df = pl.DataFrame({"interval_start": [t for t in ts if t != ts[5]]})
    missing = check_missing_intervals(
        df, "interval_start", ts[0], ts[0] + dt.timedelta(days=1), "1h"
    )
    assert missing == [ts[5]]


def test_check_missing_intervals_none_when_complete():
    ts = _hourly_range(dt.datetime(2025, 6, 1), dt.datetime(2025, 6, 2))
    df = pl.DataFrame({"interval_start": ts})
    missing = check_missing_intervals(
        df, "interval_start", ts[0], ts[0] + dt.timedelta(days=1), "1h"
    )
    assert missing == []


def test_check_dst_days_clean_for_correctly_generated_year():
    # A full year generated with a DST-aware timezone naturally has 23 hours on
    # spring-forward and 25 on fall-back, so a correctly-ingested dataset should
    # report no issues.
    ts = _hourly_range(dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1))
    df = pl.DataFrame({"interval_start": ts})
    issues = check_dst_days(df, "interval_start", freq_per_day=24, year=2025)
    assert issues == []


def test_check_dst_days_flags_missing_fall_back_hour():
    # Simulate a naive pipeline that drops the repeated hour on fall-back day
    # instead of keeping both occurrences (2025-11-02 is fall-back in US/Central).
    # Use a full year so the spring-forward day is unaffected and only the
    # fall-back day is corrupted.
    ts = _hourly_range(dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1))
    seen = set()
    deduped = []
    for t in ts:
        naive_key = t.replace(tzinfo=None)
        if naive_key in seen:
            continue
        seen.add(naive_key)
        deduped.append(t)
    df = pl.DataFrame({"interval_start": deduped})
    issues = check_dst_days(df, "interval_start", freq_per_day=24, year=2025)
    assert len(issues) == 1
    assert "fall-back" in issues[0]


def test_check_dst_days_flags_extra_spring_forward_hour():
    # Simulate a naive pipeline that double-counts an hour on spring-forward day
    # (2025-03-09), giving it 24 rows instead of the correct 23. The skipped wall
    # clock hour (2am-3am) doesn't exist as a real timestamp in a DST-aware
    # timezone, so a spurious extra row is what a real bug would actually look
    # like (e.g. a duplicate), not a fabricated 2am row.
    ts = list(_hourly_range(dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1)))
    first_spring_forward_idx = next(
        i for i, t in enumerate(ts) if t.date() == dt.date(2025, 3, 9)
    )
    fabricated = ts + [ts[first_spring_forward_idx]]
    df = pl.DataFrame({"interval_start": fabricated})
    issues = check_dst_days(df, "interval_start", freq_per_day=24, year=2025)
    assert len(issues) == 1
    assert "spring-forward" in issues[0]
