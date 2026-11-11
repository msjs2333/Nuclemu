"""Transmission counting with a fixed beta source geometry and aluminium foils."""

from collections.abc import Mapping
from random import Random

from nuclemu.core import Component, Connection, Device, Experiment, Parameter
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
        Parameter("source_present", "测量模式", "", 1, 0, 1, integer=True,
                  options=((0, "本底"), (1, "有源"))),
        Parameter("foil_count", "铝箔片数（每片 0.10 mm）", "片", 0, 0, 24, integer=True),
    ),
    devices=(Device("counter", "counter", "β 计数器",
                    background_conditions={"source_present": 0}),),
    model=sample_counts,
    question="增加铝箔片数后，扣除本底的 β 计数率怎样变化？",
    guide=(
        "在源座选择本底模式，用计数器记录本底计数和实际曝光，例如 60 s。",
        "切到有源模式。先测无箔读数，再分别加入 4、8、16 片铝箔测量；每片厚 0.10 mm。"
        "不同厚度可设不同采集时间。",
        "在计数表中选择本底段，用样品率减去本底率。比较净率及其标准不确定度，"
        "估计固定几何下信号降至无箔值一半所需的厚度。",
    ),
    components=(
        Component("source", "source", "β 源座", "移开源测本底，放入源测量透射信号。", ("source_present",)),
        Component("foil", "foil", "铝箔架", "每片厚 0.10 mm，可叠放 0 至 24 片。", ("foil_count",)),
        Component("detector", "detector", "β 探测器", "在固定几何下记录到达探测器且通过甄别的脉冲。", device="counter"),
        Component("counter", "instrument", "计数器", "累加采集门内的脉冲数，并记录实际曝光。", device="counter"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 β 粒子"),
        Connection("foil", "detector", "particle", "透射 β 粒子"),
        Connection("detector", "counter", "signal", "计数脉冲"),
    ),
)
