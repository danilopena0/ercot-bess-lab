"""Market configuration and RTC+B regime tagging.

ERCOT went live with RTC+B (Real-Time Co-optimization + Batteries) on 2025-12-05.
Before that date, real-time ancillary service capacity is only cleared in the
Day-Ahead Market; batteries have no real-time AS revenue stream. After that date,
energy and AS are co-optimized every real-time interval. This boundary is a
first-class dimension throughout the pipeline, not just a display label.
"""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field

RTCB_GO_LIVE_DATE = dt.date(2025, 12, 5)

ERCOT_TIMEZONE = "US/Central"


class MarketRegime(StrEnum):
    PRE_RTCB = "pre_rtcb"
    POST_RTCB = "post_rtcb"


def regime_for_date(date: dt.date) -> MarketRegime:
    return MarketRegime.POST_RTCB if date >= RTCB_GO_LIVE_DATE else MarketRegime.PRE_RTCB


class MarketConfig(BaseModel):
    """Configuration for a data pull / backtest scope."""

    hub: str = Field(
        default="HB_HOUSTON",
        description="ERCOT settlement point (trading hub, load zone, or resource node)",
    )
    location_type: str = Field(
        default="Trading Hub",
        description="gridstatus location_type: 'Trading Hub', 'Load Zone', or 'Resource Node'",
    )
    start_date: dt.date
    end_date: dt.date

    @property
    def spans_both_regimes(self) -> bool:
        return regime_for_date(self.start_date) != regime_for_date(self.end_date)
