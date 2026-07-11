"""Data quality checks applied to silver tables before they're trusted downstream.

These are structural checks on interval-indexed timeseries: are the intervals
contiguous at the expected cadence, are there duplicate timestamps, and — because
ERCOT operates in US/Central, which observes DST — do the spring-forward (23-hour)
and fall-back (25-hour) days have the right interval count instead of silently
losing or duplicating an hour.
"""

import datetime as dt
from dataclasses import dataclass, field

import polars as pl


@dataclass
class DQReport:
    dataset: str
    missing_intervals: list[dt.datetime] = field(default_factory=list)
    duplicate_timestamps: list[dt.datetime] = field(default_factory=list)
    dst_day_issues: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.missing_intervals or self.duplicate_timestamps or self.dst_day_issues)


def check_duplicate_timestamps(
    df: pl.DataFrame, ts_col: str, group_cols: list[str] | None = None
) -> list[dt.datetime]:
    """Timestamps that appear more than once (within each group, if given)."""
    keys = [*(group_cols or []), ts_col]
    dupes = (
        df.group_by(keys)
        .agg(pl.len().alias("_n"))
        .filter(pl.col("_n") > 1)
        .sort(ts_col)
    )
    return dupes.get_column(ts_col).to_list()


def check_missing_intervals(
    df: pl.DataFrame,
    ts_col: str,
    start: dt.datetime,
    end: dt.datetime,
    freq: str,
) -> list[dt.datetime]:
    """Interval starts absent from df within [start, end), at the given Polars freq
    string (e.g. "1h", "15m"), correctly expanding across DST transitions since
    the expected range is generated in the same tz-aware timestamp space as df.
    """
    expected = pl.datetime_range(
        start, end, interval=freq, time_zone=str(start.tzinfo), closed="left", eager=True
    )
    actual = set(df.get_column(ts_col).to_list())
    return sorted(t for t in expected.to_list() if t not in actual)


def _dst_days_for_year(year: int) -> list[tuple[dt.date, str, int]]:
    """(date, label, expected_delta_from_normal_day) for a year's two DST transitions.

    DST transition dates are computed rather than hardcoded: US DST starts on the
    second Sunday in March and ends on the first Sunday in November.
    """
    return [
        (_second_sunday_march(year), "spring-forward", -1),
        (_first_sunday_november(year), "fall-back", +1),
    ]


def _check_single_dst_day(
    df: pl.DataFrame, ts_col: str, freq_per_day: int, date: dt.date, label: str, expected_delta: int
) -> str | None:
    day_count = df.filter(pl.col(ts_col).dt.date() == date).height
    expected = freq_per_day + expected_delta
    if day_count != expected:
        return f"{label} day {date}: expected {expected} intervals, found {day_count}"
    return None


def check_dst_days(df: pl.DataFrame, ts_col: str, freq_per_day: int, year: int) -> list[str]:
    """Verify the US/Central spring-forward and fall-back days have the expected
    interval count: one fewer interval on spring-forward, one more on fall-back,
    relative to a normal day's `freq_per_day` intervals.
    """
    issues = [
        issue
        for date, label, expected_delta in _dst_days_for_year(year)
        if (issue := _check_single_dst_day(df, ts_col, freq_per_day, date, label, expected_delta))
    ]
    return issues


def _second_sunday_march(year: int) -> dt.date:
    d = dt.date(year, 3, 1)
    candidates = [d + dt.timedelta(days=i) for i in range(31)]
    sundays = [c for c in candidates if c.month == 3 and c.weekday() == 6]
    return sundays[1]


def _first_sunday_november(year: int) -> dt.date:
    d = dt.date(year, 11, 1)
    for i in range(7):
        candidate = d + dt.timedelta(days=i)
        if candidate.weekday() == 6:
            return candidate
    raise AssertionError("unreachable")


def run_dq_checks(
    df: pl.DataFrame,
    dataset: str,
    ts_col: str,
    start: dt.datetime,
    end: dt.datetime,
    freq: str,
    freq_per_day: int,
    group_cols: list[str] | None = None,
) -> DQReport:
    report = DQReport(dataset=dataset)
    report.duplicate_timestamps = check_duplicate_timestamps(df, ts_col, group_cols)
    report.missing_intervals = check_missing_intervals(df, ts_col, start, end, freq)

    # Only check a DST transition day if it actually falls within the queried
    # range — otherwise a short, DST-free range would spuriously "find 0"
    # intervals for a day it was never asked to cover.
    query_start_date, query_end_date = start.date(), end.date()  # end is exclusive
    for year in {start.year, end.year}:
        for date, label, expected_delta in _dst_days_for_year(year):
            if query_start_date <= date < query_end_date:
                issue = _check_single_dst_day(df, ts_col, freq_per_day, date, label, expected_delta)
                if issue:
                    report.dst_day_issues.append(issue)
    return report
