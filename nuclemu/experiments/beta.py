"""Transmission counting with a fixed beta source geometry and aluminium foils."""

from collections.abc import Mapping
from random import Random

from nuclemu.core import Device, Experiment, Parameter
from nuclemu.physics import AluminumFoil, poisson


FOIL_THICKNESS_MM = 0.10
HALF_VALUE_AREAL_DENSITY_G_CM2 = 0.112
UNATTENUATED_SIGNAL_CPS = 100.0
BACKGROUND_CPS = 2.0


def sample_counts(
    settings: Mapping[str, int | float], start_s: float, end_s: float, rng: Random
) -> dict[str, tuple[int, ...]]:
    rate = BACKGROUND_CPS
    if settings["source_present"]:
        foil = AluminumFoil(settings["foil_count"] * FOIL_THICKNESS_MM)
        half_value_layers = foil.areal_density_g_cm2 / HALF_VALUE_AREAL_DENSITY_G_CM2
        rate += UNATTENUATED_SIGNAL_CPS * 2.0 ** (-half_value_layers)
    return {"counter": (poisson(rate * (end_s - start_s), rng),)}


EXPERIMENT = Experiment(
    id="beta",
    title="β 射线吸收",
    description="测量本底，在相同几何下加入铝箔，比较单位时间内记录的净计数。",
    parameters=(
        Parameter("source_present", "测量模式（0 本底，1 有源）", "", 1, 0, 1, integer=True),
        Parameter("foil_count", "铝箔片数（每片 0.10 mm）", "片", 0, 0, 24, integer=True),
    ),
    devices=(Device("counter", "counter", "β 计数器"),),
    model=sample_counts,
)
