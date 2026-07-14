"""Golden-case tests for the perfect-foresight LP: tiny problems small enough to solve
by hand, so the expected values below are independently derived, not just "whatever the
solver produced." A regression here means the LP formulation itself is wrong, not that
some numerical tolerance drifted.
"""

import datetime as dt

import pytest

from ercot_bess.models.battery import BatterySpec
from ercot_bess.optimize.perfect_foresight import solve_perfect_foresight


def _hours(n: int, start: dt.datetime = dt.datetime(2025, 6, 1, 0)) -> list[dt.datetime]:
    return [start + dt.timedelta(hours=i) for i in range(n)]


def test_basic_arbitrage_no_losses():
    # Hand-solvable: charge at the two $10 intervals, discharge at the two $50
    # intervals. No losses, no degradation, no binding cycle limit.
    # Revenue = (50-10)*1 + (50-10)*1 = 80.
    battery = BatterySpec(
        power_mw=1, energy_mwh=1, round_trip_efficiency=1.0,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=100, degradation_cost_per_mwh=0,
    )
    result = solve_perfect_foresight(
        interval_start=_hours(4),
        energy_price_usd_per_mwh=[10, 50, 10, 50],
        battery=battery,
        interval_hours=1.0,
    )
    assert result.total_revenue_usd == pytest.approx(80.0)
    assert result.charge_mw[0] == pytest.approx(1.0)
    assert result.discharge_mw[1] == pytest.approx(1.0)
    assert result.charge_mw[2] == pytest.approx(1.0)
    assert result.discharge_mw[3] == pytest.approx(1.0)


def test_efficiency_losses_reduce_revenue():
    # eta = sqrt(0.81) = 0.9 exactly. Charging 1MW for 1h fills SoC to 0.9 MWh
    # (energy_mwh=10 is non-binding, isolating the efficiency effect). Discharging
    # is then SoC-limited, not power-limited: max discharge = soc * eta / dt =
    # 0.9*0.9 = 0.81 MW, delivering 0.81 MWh to the grid.
    # Cost: 2 x (1 MWh @ $10) = $20. Revenue: 2 x (0.81 MWh @ $50) = $81. Net = $61.
    battery = BatterySpec(
        power_mw=1, energy_mwh=10, round_trip_efficiency=0.81,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=100, degradation_cost_per_mwh=0,
    )
    result = solve_perfect_foresight(
        interval_start=_hours(4),
        energy_price_usd_per_mwh=[10, 50, 10, 50],
        battery=battery,
        interval_hours=1.0,
    )
    assert result.total_revenue_usd == pytest.approx(61.0, abs=1e-4)
    assert result.total_revenue_usd < 80.0  # strictly less than the no-loss case


def test_daily_cycle_limit_caps_throughput():
    # cycle limit = 0.5 cycles * 1 MWh = 0.5 MWh of discharge allowed for the whole
    # day. Optimal: charge 0.5 MWh at the cheapest price ($10), discharge 0.5 MWh at
    # the priciest price ($50). Net = 0.5*50 - 0.5*10 = 25 - 5 = $20 — additional
    # charge/discharge at the other $10/$50 pair earns nothing once the 0.5 MWh
    # discharge cap for the day is used up.
    battery = BatterySpec(
        power_mw=1, energy_mwh=1, round_trip_efficiency=1.0,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=0.5, degradation_cost_per_mwh=0,
    )
    result = solve_perfect_foresight(
        interval_start=_hours(4),
        energy_price_usd_per_mwh=[10, 50, 10, 50],
        battery=battery,
        interval_hours=1.0,
    )
    assert result.total_revenue_usd == pytest.approx(20.0)
    assert sum(result.discharge_mw) * 1.0 == pytest.approx(0.5)


def test_degradation_cost_can_make_trading_unprofitable():
    # Spread is $20/MWh ($30 - $10), but degradation cost is $25/MWh applied to
    # *both* legs — a full round trip costs 2*$25=$50 in degradation against only
    # $20 of gross arbitrage revenue. Marginal profit per MWh cycled is negative,
    # so the optimal dispatch is to never trade at all.
    battery = BatterySpec(
        power_mw=1, energy_mwh=1, round_trip_efficiency=1.0,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=100, degradation_cost_per_mwh=25,
    )
    result = solve_perfect_foresight(
        interval_start=_hours(4),
        energy_price_usd_per_mwh=[10, 30, 10, 30],
        battery=battery,
        interval_hours=1.0,
    )
    assert result.total_revenue_usd == pytest.approx(0.0, abs=1e-6)
    assert result.charge_mw == pytest.approx([0, 0, 0, 0], abs=1e-6)
    assert result.discharge_mw == pytest.approx([0, 0, 0, 0], abs=1e-6)


def test_as_co_optimization_awards_full_headroom_when_energy_is_flat():
    # Energy price is flat at $0 (no arbitrage value whatsoever), so the entire
    # power envelope is free to dedicate to RegUp capacity, which pays $5/MW-hr
    # under the no-deployment-energy assumption. Expected: full 1MW awarded to
    # RegUp every interval, revenue = 4 x 1MW x $5 = $20.
    battery = BatterySpec(
        power_mw=1, energy_mwh=1, round_trip_efficiency=1.0,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=100, degradation_cost_per_mwh=0,
    )
    result = solve_perfect_foresight(
        interval_start=_hours(4),
        energy_price_usd_per_mwh=[0, 0, 0, 0],
        battery=battery,
        interval_hours=1.0,
        as_prices_usd_per_mw={"RegUp": [5, 5, 5, 5]},
    )
    assert result.as_revenue_usd == pytest.approx(20.0)
    assert result.as_awards_mw["RegUp"] == pytest.approx([1, 1, 1, 1])
    assert result.total_revenue_usd == pytest.approx(20.0)


def test_as_revenue_is_never_negative_and_adds_to_energy_only_baseline():
    # Invariant: co-optimizing AS on top of an energy-arbitrage problem can only
    # help (or be neutral), never hurt — the LP could always fall back to zero AS
    # award and recover exactly the energy-only revenue.
    battery = BatterySpec(
        power_mw=1, energy_mwh=1, round_trip_efficiency=1.0,
        min_soc_fraction=0, max_soc_fraction=1,
        daily_cycle_limit=100, degradation_cost_per_mwh=0,
    )
    prices = [10, 50, 10, 50]
    ts = _hours(4)

    energy_only = solve_perfect_foresight(ts, prices, battery, interval_hours=1.0)
    with_as = solve_perfect_foresight(
        ts, prices, battery, interval_hours=1.0,
        as_prices_usd_per_mw={"RegUp": [2, 2, 2, 2], "RegDown": [1, 1, 1, 1]},
    )

    assert with_as.total_revenue_usd >= energy_only.total_revenue_usd - 1e-6
