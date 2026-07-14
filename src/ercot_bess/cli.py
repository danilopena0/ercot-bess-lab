"""Command-line entry point: `ercot-bess ingest`, `ercot-bess transform`, `ercot-bess dq`,
`ercot-bess optimize`.

Backtest/report commands land in later milestones.
"""

import datetime as dt
import logging

import typer

from ercot_bess.ingest.pipeline import run_ingestion
from ercot_bess.ingest.raw_cache import RawCache
from ercot_bess.models.battery import BatterySpec
from ercot_bess.models.market import MarketConfig
from ercot_bess.optimize.data_loading import load_dam_as_price_series, load_spp_series
from ercot_bess.optimize.perfect_foresight import solve_perfect_foresight
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


@app.command()
def optimize(
    start: str = typer.Option(..., help="Start date, YYYY-MM-DD"),
    end: str = typer.Option(..., help="End date, YYYY-MM-DD (inclusive)"),
    hub: str = typer.Option("HB_HOUSTON", help="Settlement point / trading hub"),
    power_mw: float = typer.Option(100.0, help="Battery power rating (MW)"),
    energy_mwh: float = typer.Option(200.0, help="Battery energy capacity (MWh)"),
) -> None:
    """Solve the perfect-foresight dispatch LP: RTM-only, DAM-only, and DAM+AS
    co-optimized variants, over already-ingested silver data. This is the revenue
    ceiling — the denominator of "% of perfect revenue" — not a real strategy.
    """
    con = register_silver_views()
    start_date, end_date = _parse_date(start), _parse_date(end)
    battery = BatterySpec(power_mw=power_mw, energy_mwh=energy_mwh)

    rtm_ts, rtm_prices = load_spp_series(con, "silver_rtm_spp", hub, start_date, end_date)
    rtm_result = solve_perfect_foresight(rtm_ts, rtm_prices, battery, interval_hours=0.25)

    dam_ts, dam_prices = load_spp_series(con, "silver_dam_spp", hub, start_date, end_date)
    dam_result = solve_perfect_foresight(dam_ts, dam_prices, battery, interval_hours=1.0)

    as_prices = load_dam_as_price_series(con, dam_ts, start_date, end_date)
    dam_as_result = solve_perfect_foresight(
        dam_ts, dam_prices, battery, interval_hours=1.0, as_prices_usd_per_mw=as_prices
    )

    typer.echo(f"Perfect-foresight dispatch, {hub}, {start}..{end}, {power_mw}MW/{energy_mwh}MWh:")
    typer.echo(f"  RTM-only:        ${rtm_result.total_revenue_usd:,.0f}")
    typer.echo(f"  DAM-only:        ${dam_result.total_revenue_usd:,.0f}")
    as_energy = dam_as_result.energy_revenue_usd
    as_revenue = dam_as_result.as_revenue_usd
    as_degradation = dam_as_result.degradation_cost_usd
    typer.echo(
        f"  DAM + AS:        ${dam_as_result.total_revenue_usd:,.0f}"
        f"  (energy ${as_energy:,.0f} + AS ${as_revenue:,.0f} - degradation ${as_degradation:,.0f})"
    )


if __name__ == "__main__":
    app()
