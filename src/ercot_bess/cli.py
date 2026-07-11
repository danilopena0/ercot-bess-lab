"""Command-line entry point: `ercot-bess ingest`, `ercot-bess transform`, `ercot-bess dq`.

M1 scope only wires ingest → transform → dq. Optimize/backtest/report commands
land in later milestones.
"""

import datetime as dt
import logging

import typer

from ercot_bess.ingest.pipeline import run_ingestion
from ercot_bess.ingest.raw_cache import RawCache
from ercot_bess.models.market import MarketConfig
from ercot_bess.transform.dq import run_dq_checks
from ercot_bess.transform.duckdb_store import register_silver_views
from ercot_bess.transform.silver import build_silver_table

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="ERCOT BESS dispatch backtester")

# (dataset, timestamp resolution, intervals per day) used for DQ checks.
_DQ_SPEC = {
    "dam_spp": ("1h", 24),
    "rtm_spp": ("15m", 96),
    "load": ("1h", 24),
    "dam_as_prices": ("1h", 24),
    "rtm_as_prices": ("15m", 96),
}


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


@app.command()
def ingest(
    start: str = typer.Option(..., help="Start date, YYYY-MM-DD"),
    end: str = typer.Option(..., help="End date, YYYY-MM-DD (inclusive)"),
    hub: str = typer.Option("HB_HOUSTON", help="Settlement point / trading hub"),
) -> None:
    """Incrementally pull DAM/RTM SPP, load, and AS clearing prices into data/raw."""
    config = MarketConfig(hub=hub, start_date=_parse_date(start), end_date=_parse_date(end))
    results = run_ingestion(config)
    typer.echo("Ingestion complete:")
    for dataset, count in results.items():
        typer.echo(f"  {dataset}: {count} new raw file(s) written")


@app.command()
def transform(
    start: str = typer.Option(..., help="Start date, YYYY-MM-DD"),
    end: str = typer.Option(..., help="End date, YYYY-MM-DD (inclusive)"),
) -> None:
    """Build silver tables from cached raw data and register them in DuckDB."""
    raw_cache = RawCache()
    start_date, end_date = _parse_date(start), _parse_date(end)
    for dataset in _DQ_SPEC:
        df = build_silver_table(dataset, start_date, end_date, raw_cache)
        typer.echo(f"  {dataset}: {df.height} silver row(s) written for {start}..{end}")
    register_silver_views()
    typer.echo("Registered silver views in DuckDB at data/ercot.duckdb")


@app.command()
def dq(
    start: str = typer.Option(..., help="Start date, YYYY-MM-DD"),
    end: str = typer.Option(..., help="End date, YYYY-MM-DD (inclusive)"),
) -> None:
    """Run data quality checks against the silver tables for a date range."""
    con = register_silver_views()
    start_date, end_date = _parse_date(start), _parse_date(end)

    all_clean = True
    for dataset, (freq, freq_per_day) in _DQ_SPEC.items():
        try:
            df = con.execute(f"SELECT * FROM silver_{dataset}").pl()
        except Exception:
            typer.echo(f"  {dataset}: no silver table registered, skipping")
            continue
        if df.height == 0:
            typer.echo(f"  {dataset}: empty, skipping")
            continue

        group_cols: list[str] = [c for c in ("location", "product", "zone") if c in df.columns]
        tz = df.get_column("interval_start")[0].tzinfo
        start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=tz)
        end_dt = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min, tzinfo=tz)

        report = run_dq_checks(
            df, dataset, "interval_start", start_dt, end_dt, freq, freq_per_day, group_cols
        )
        status = "CLEAN" if report.is_clean else "ISSUES"
        all_clean &= report.is_clean
        typer.echo(f"  {dataset}: {status}")
        if report.missing_intervals:
            typer.echo(f"    missing intervals: {len(report.missing_intervals)}")
        if report.duplicate_timestamps:
            typer.echo(f"    duplicate timestamps: {len(report.duplicate_timestamps)}")
        for issue in report.dst_day_issues:
            typer.echo(f"    dst issue: {issue}")

    if not all_clean:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
