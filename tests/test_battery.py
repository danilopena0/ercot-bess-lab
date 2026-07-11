import pytest

from ercot_bess.models.battery import BatterySpec


def test_defaults_match_spec():
    spec = BatterySpec()
    assert spec.power_mw == 100.0
    assert spec.energy_mwh == 200.0
    assert spec.round_trip_efficiency == 0.86
    assert spec.daily_cycle_limit == 1.5
    assert spec.degradation_cost_per_mwh == 2.0


def test_usable_energy_respects_soc_bounds():
    spec = BatterySpec(energy_mwh=200.0, min_soc_fraction=0.1, max_soc_fraction=0.9)
    assert spec.usable_energy_mwh == pytest.approx(160.0)
    assert spec.min_soc_mwh == pytest.approx(20.0)
    assert spec.max_soc_mwh == pytest.approx(180.0)


def test_one_way_efficiency_is_sqrt_of_round_trip():
    spec = BatterySpec(round_trip_efficiency=0.81)
    assert spec.one_way_efficiency == pytest.approx(0.9)


def test_rejects_inverted_soc_bounds():
    with pytest.raises(ValueError):
        BatterySpec(min_soc_fraction=0.9, max_soc_fraction=0.1)


def test_rejects_non_positive_power():
    with pytest.raises(ValueError):
        BatterySpec(power_mw=0)
