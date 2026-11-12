"""Transmission counting with a fixed beta source geometry and aluminium foils."""

from collections.abc import Mapping
from random import Random

from nuclemu.core import Component, Connection, Device, Experiment, Parameter, SignalOutput
from nuclemu.physics import AluminumFoil, poisson


FOIL_THICKNESS_MM = 0.10
DETECTOR_OUTPUT = "beta_detector"
HALF_VALUE_AREAL_DENSITY_G_CM2 = 0.112
UNATTENUATED_SIGNAL_CPS = 100.0
BACKGROUND_CPS = 2.0


def sample_counts(
    settings: Mapping[str, int | float], start_s: float, end_s: float, rng: Random
) -> dict[str, tuple[int, ...]]:
    rate = BACKGROUND_CPS
    if settings["source_present"]:
        foil = AluminumFoil(settings["foil_count"] *
                            settings.get("foil_spec_um", FOIL_THICKNESS_MM * 1000) / 1000)
        half_value_layers = foil.areal_density_g_cm2 / HALF_VALUE_AREAL_DENSITY_G_CM2
        rate += UNATTENUATED_SIGNAL_CPS * 2.0 ** (-half_value_layers)
    return {DETECTOR_OUTPUT: (poisson(rate * (end_s - start_s), rng),)}


EXPERIMENT = Experiment(
    id="beta",
    title="β 射线吸收",
    description="测量本底，在相同几何下加入铝箔，比较单位时间内记录的净计数。",
    parameters=(
        Parameter("source_present", "源座", "", 1, 0, 1, integer=True,
                  options=((0, "空源座"), (1, "β 源"))),
        Parameter("foil_count", "铝箔片数", "片", 0, 0, 24, integer=True),
        Parameter("foil_spec_um", "铝箔单片规格", "µm/片", 100, 50, 100, integer=True,
                  options=((50, "50 µm/片"), (100, "100 µm/片"))),
    ),
    devices=(Device("counter", "counter", "β 计数器 A",
                    background_conditions={"source_present": 0}, input=DETECTOR_OUTPUT),
             Device("counter_b", "counter", "β 计数器 B",
                    background_conditions={"source_present": 0}, input=DETECTOR_OUTPUT)),
    model=sample_counts,
    outputs=(SignalOutput(DETECTOR_OUTPUT, "β 探测器输出", response=
                         "固定几何、阈值、探测效率及源窗已计入有效吸收计数率；含环境本底。"
                         "两台计数器理想无损分接，不再乘效率。"),),
    question="增加铝箔片数后，扣除本底的 β 计数率怎样变化？",
    guide=(
        "在装置源座选择空源座，开启探测器输出，用计数器记录本底计数和实际曝光，例如 60 s。",
        "放入 β 源。先测无箔读数，再分别加入 4、8、16 片铝箔测量；默认每片厚 100 µm。"
        "不同厚度可设不同采集时间。",
        "两台计数器可独立采集同一探测输入。同期 A 的两个连续 5 s 窗之和应等于 B 的一个 10 s 窗。",
        "在计数表中选择本底段，用样品率减去本底率。比较净率及其标准不确定度，"
        "估计固定几何下信号降至无箔值一半所需的厚度。",
    ),
    components=(
        Component("source", "source", "β 源座", "空源座仍可测环境本底；放入 β 源测量透射信号。", ("source_present",), illustration="source"),
        Component("foil", "foil", "铝箔架", "Al 教学选定规格 50 或 100 µm/片，默认 100 µm；可叠放 0 至 24 片。"
                  "0 片为空箔，总厚度为单片规格乘片数，空箔与空源独立。", ("foil_spec_um", "foil_count"), illustration="foil"),
        Component("detector", "detector", "β 探测器", "在固定几何下记录到达探测器且通过甄别的脉冲。",
                  output=DETECTOR_OUTPUT, illustration="beta-probe"),
        Component("counter", "instrument", "计数器 A", "独立采集门接收共用探测输出，记录本窗整数计数与实际曝光。", device="counter", illustration="counter"),
        Component("counter_b", "instrument", "计数器 B", "与 A 理想无损分接同一输出；A 停止不影响本仪器继续采集。", device="counter_b", illustration="counter"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 β 粒子"),
        Connection("foil", "detector", "particle", "透射 β 粒子"),
        Connection("detector", "counter", "signal", "计数脉冲"),
        Connection("detector", "counter_b", "signal", "同一计数脉冲分接"),
    ),
)
