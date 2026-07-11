"""Battery specification used by the optimizer and settlement calculator."""

from pydantic import BaseModel, Field, model_validator


class BatterySpec(BaseModel):
    """Physical and economic parameters of a single BESS asset.

    Defaults are a generic 2-hour-duration grid-scale battery, representative of the
    bulk of ERCOT's interconnected storage fleet as of 2025.
    """

    power_mw: float = Field(default=100.0, gt=0, description="Max charge/discharge power (MW)")
    energy_mwh: float = Field(default=200.0, gt=0, description="Usable energy capacity (MWh)")
    round_trip_efficiency: float = Field(
        default=0.86, gt=0, le=1, description="AC-to-AC round-trip efficiency"
    )
    min_soc_fraction: float = Field(
        default=0.0, ge=0, lt=1, description="Minimum state of charge, as a fraction of energy_mwh"
    )
    max_soc_fraction: float = Field(
        default=1.0, gt=0, le=1, description="Maximum state of charge, as a fraction of energy_mwh"
    )
    daily_cycle_limit: float = Field(
        default=1.5, gt=0, description="Max full-equivalent-cycles of throughput per day"
    )
    degradation_cost_per_mwh: float = Field(
        default=2.0,
        ge=0,
        description="Throughput cost applied per MWh charged or discharged ($/MWh)",
    )

    @model_validator(mode="after")
    def _check_soc_bounds(self) -> "BatterySpec":
        if self.min_soc_fraction >= self.max_soc_fraction:
            raise ValueError("min_soc_fraction must be < max_soc_fraction")
        return self

    @property
    def one_way_efficiency(self) -> float:
        """Efficiency applied on each of the charge and discharge legs.

        Round-trip efficiency is split evenly across the charge and discharge legs
        (each leg applies sqrt(RTE)), the standard convention when only a single
        RTE figure is available rather than separate charge/discharge curves.
        """
        return float(self.round_trip_efficiency**0.5)

    @property
    def usable_energy_mwh(self) -> float:
        return self.energy_mwh * (self.max_soc_fraction - self.min_soc_fraction)

    @property
    def min_soc_mwh(self) -> float:
        return self.energy_mwh * self.min_soc_fraction

    @property
    def max_soc_mwh(self) -> float:
        return self.energy_mwh * self.max_soc_fraction
