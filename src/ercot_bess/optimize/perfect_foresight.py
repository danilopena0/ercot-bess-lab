"""Perfect-foresight dispatch: the revenue a price-taker battery could earn with full
hindsight of realized prices. This is the denominator of the headline "% of perfect
revenue" metric the whole project is built around — every causal strategy in M3 is
measured against this ceiling.

Formulated as a linear program (not MILP): simultaneous charging and discharging in the
same interval is never optimal for a price-taking arbitrageur once efficiency losses and
a per-MWh degradation cost are in the objective (doing both nets strictly worse than doing
neither), so no binary "not both" constraint is needed — this keeps the LP fast to solve
even over a full month of 15-minute intervals.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np

from ercot_bess.models.battery import BatterySpec

# ERCOT AS products split by direction: "up" products reserve capacity to increase
# output (or decrease consumption) when called, competing with discharge headroom;
# "down" (RegDown) reserves capacity to decrease output (increase consumption),
# competing with charge headroom.
UP_AS_PRODUCTS = ("RegUp", "RRS", "ECRS", "NonSpin")
DOWN_AS_PRODUCTS = ("RegDown",)


@dataclass
class DispatchResult:
    interval_start: list[dt.datetime]
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    # length T+1: state of charge at the start of each interval, plus the final value
    soc_mwh: np.ndarray
    energy_revenue_usd: float
    degradation_cost_usd: float
    as_revenue_usd: float = 0.0
    as_awards_mw: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def total_revenue_usd(self) -> float:
        return self.energy_revenue_usd + self.as_revenue_usd - self.degradation_cost_usd


def _group_indices_by_day(interval_start: Sequence[dt.datetime]) -> dict[dt.date, list[int]]:
    groups: dict[dt.date, list[int]] = {}
    for i, ts in enumerate(interval_start):
        groups.setdefault(ts.date(), []).append(i)
    return groups


def solve_perfect_foresight(
    interval_start: Sequence[dt.datetime],
    energy_price_usd_per_mwh: Sequence[float],
    battery: BatterySpec,
    interval_hours: float,
    initial_soc_mwh: float | None = None,
    as_prices_usd_per_mw: Mapping[str, Sequence[float]] | None = None,
) -> DispatchResult:
    """Solve the perfect-foresight dispatch LP over a realized price series.

    Args:
        interval_start: timestamps for each interval (used to group the daily cycle
            limit by calendar day — a real per-day operating constraint, not just an
            average rate over the whole horizon).
        energy_price_usd_per_mwh: realized settlement point prices (RTM or DAM — pass
            whichever series `interval_hours` matches).
        battery: physical/economic battery parameters.
        interval_hours: length of each interval in hours (0.25 for RTM, 1.0 for DAM).
        initial_soc_mwh: starting state of charge. Defaults to the battery's minimum
            SoC (an uncommitted, empty starting state) — a deliberate simplifying
            assumption, not a claim about any particular real starting condition.
        as_prices_usd_per_mw: optional DAM AS clearing prices by product name (e.g.
            "RegUp", "RegDown", "RRS", "ECRS", "NonSpin"), each the same length as
            `energy_price_usd_per_mwh`. When given, AS capacity revenue is
            co-optimized alongside energy arbitrage under two simplifying
            assumptions: (1) AS capacity is paid for at the clearing price with no
            deployment energy modeled — the battery is never actually called to
            deliver, only paid to reserve capacity; (2) the battery is a
            price-taker in both markets. See ADR 0006 for the full reasoning.

    Returns:
        DispatchResult with the optimal charge/discharge/SoC trajectory and a
        revenue breakdown by stream.
    """
    n_intervals = len(energy_price_usd_per_mwh)
    if len(interval_start) != n_intervals:
        raise ValueError("interval_start and energy_price_usd_per_mwh must be the same length")

    charge = cp.Variable(n_intervals, nonneg=True)
    discharge = cp.Variable(n_intervals, nonneg=True)
    soc = cp.Variable(n_intervals + 1)

    eta = battery.one_way_efficiency
    start_soc = battery.min_soc_mwh if initial_soc_mwh is None else initial_soc_mwh

    constraints = [
        charge <= battery.power_mw,
        discharge <= battery.power_mw,
        soc[0] == start_soc,
        soc >= battery.min_soc_mwh,
        soc <= battery.max_soc_mwh,
        soc[1:] == soc[:-1] + charge * eta * interval_hours - discharge / eta * interval_hours,
    ]

    daily_cycle_cap = battery.daily_cycle_limit * battery.energy_mwh
    for _day, idx in _group_indices_by_day(interval_start).items():
        constraints.append(cp.sum(discharge[idx]) * interval_hours <= daily_cycle_cap)

    energy_price = np.asarray(energy_price_usd_per_mwh, dtype=float)
    energy_revenue_expr = cp.sum(cp.multiply(discharge - charge, energy_price)) * interval_hours
    degradation_rate = battery.degradation_cost_per_mwh
    degradation_expr = degradation_rate * cp.sum(charge + discharge) * interval_hours

    as_award_vars: dict[str, cp.Variable] = {}
    as_revenue_expr = None
    if as_prices_usd_per_mw:
        for product, prices in as_prices_usd_per_mw.items():
            prices_arr = np.asarray(prices, dtype=float)
            if len(prices_arr) != n_intervals:
                raise ValueError(f"AS price series for {product!r} must match energy price length")
            award = cp.Variable(n_intervals, nonneg=True)
            as_award_vars[product] = award
            term = cp.sum(cp.multiply(award, prices_arr)) * interval_hours
            as_revenue_expr = term if as_revenue_expr is None else as_revenue_expr + term

        up_awards = [as_award_vars[p] for p in UP_AS_PRODUCTS if p in as_award_vars]
        if up_awards:
            constraints.append(discharge + sum(up_awards) <= battery.power_mw)
        down_awards = [as_award_vars[p] for p in DOWN_AS_PRODUCTS if p in as_award_vars]
        if down_awards:
            constraints.append(charge + sum(down_awards) <= battery.power_mw)

    objective_expr = energy_revenue_expr - degradation_expr
    if as_revenue_expr is not None:
        objective_expr = objective_expr + as_revenue_expr

    problem = cp.Problem(cp.Maximize(objective_expr), constraints)
    problem.solve(solver=cp.HIGHS)

    if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        raise RuntimeError(f"Perfect-foresight LP did not solve: status={problem.status}")

    return DispatchResult(
        interval_start=list(interval_start),
        charge_mw=charge.value,
        discharge_mw=discharge.value,
        soc_mwh=soc.value,
        energy_revenue_usd=float(energy_revenue_expr.value),
        degradation_cost_usd=float(degradation_expr.value),
        as_revenue_usd=float(as_revenue_expr.value) if as_revenue_expr is not None else 0.0,
        as_awards_mw={p: v.value for p, v in as_award_vars.items()},
    )
