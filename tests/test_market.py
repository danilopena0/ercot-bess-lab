import datetime as dt

from ercot_bess.models.market import MarketConfig, MarketRegime, regime_for_date


def test_regime_boundary_is_exclusive_of_pre():
    assert regime_for_date(dt.date(2025, 12, 4)) == MarketRegime.PRE_RTCB
    assert regime_for_date(dt.date(2025, 12, 5)) == MarketRegime.POST_RTCB
    assert regime_for_date(dt.date(2025, 12, 6)) == MarketRegime.POST_RTCB


def test_spans_both_regimes():
    config = MarketConfig(start_date=dt.date(2025, 11, 1), end_date=dt.date(2025, 12, 31))
    assert config.spans_both_regimes is True


def test_does_not_span_regimes_within_pre():
    config = MarketConfig(start_date=dt.date(2025, 6, 1), end_date=dt.date(2025, 6, 30))
    assert config.spans_both_regimes is False


def test_default_hub_is_houston():
    config = MarketConfig(start_date=dt.date(2025, 6, 1), end_date=dt.date(2025, 6, 30))
    assert config.hub == "HB_HOUSTON"
