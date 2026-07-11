# 0005: HB_HOUSTON as the default settlement point

**Status:** Accepted (M1)

## Context

Real commercial battery optimizers (Habitat Energy, Jupiter Power, Tesla Autobidder)
settle at the specific resource node of the physical asset, not a hub — a hub price is an
aggregate/proxy used for benchmarking, not actual settlement. This project needs a single
default settlement point for M1–M3 (configurable later) that's a reasonable proxy for real
battery economics without being either too noisy for early debugging or too disconnected
from where batteries actually operate.

Real ERCOT battery buildout concentrates at two hubs, for different reasons:

- **HB_WEST**: largest concentration, driven by wind-congestion negative pricing in the
  Permian Basin/West Texas wind belt — the widest arbitrage spreads, and correspondingly
  the noisiest price signal.
- **HB_HOUSTON**: second-largest concentration, driven by CenterPoint transmission
  congestion and coastal load growth outpacing infrastructure. Still volatile, but less
  extreme, and it's the hub most industry BESS-revenue benchmarks (e.g. Modo Energy's
  ERCOT storage index) anchor to.
- **HB_NORTH**: most liquid, closest to "ERCOT average," but least representative of
  actual battery siting or economics.

## Decision

Default to `HB_HOUSTON` (`MarketConfig.hub` default in `models/market.py`), chosen over
HB_WEST specifically to trade a slightly less dramatic arbitrage story for a less noisy
signal during early development (golden-case tests, DQ checks, debugging), while staying
recognizable to a hiring-manager audience already familiar with industry BESS benchmarks.
Fully configurable per run — nothing in the pipeline hardcodes HB_HOUSTON beyond this
default.

## Consequences

- M1's ingested data and validation numbers (see the M1 write-up) are for HB_HOUSTON. Any
  hub-specific findings (e.g. the RTM SPP Load Zone duplicate-row issue, which affects
  Load Zone locations but not Trading Hub locations like HB_HOUSTON) may not generalize to
  every settlement point without re-checking.
- If the project's narrative shifts toward "maximum arbitrage story," switching the
  default to HB_WEST is a one-line change with no structural rework — regime tagging, DQ
  checks, and the silver schema are all hub-agnostic.
