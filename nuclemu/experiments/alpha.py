"""Alpha energy loss in aluminium, observed with a silicon spectrometer."""

import math
from bisect import bisect_left
from random import Random
from typing import Mapping

from nuclemu.core import Component, Connection, Device, Experiment, Parameter, SignalOutput
from nuclemu.physics import AluminumFoil, poisson


# Selected NIST ASTAR SRD 124 aluminium CSDA ranges (MeV, g/cm²).
# https://physics.nist.gov/PhysRefData/Star/Text/ASTAR-t.html (Aluminum, 013)
# The zero-energy endpoint is an added boundary; see docs/alpha.md.
RANGE_TABLE = (
    (0.0, 0.0),
    (0.001, 9.964e-6),
    (0.01, 5.381e-5),
    (0.05, 1.418e-4),
    (0.1, 2.059e-4),
    (0.25, 3.447e-4),
    (0.5, 5.421e-4),
    (0.75, 7.351e-4),
    (1.0, 9.343e-4),
    (1.5, 1.365e-3),
    (2.0, 1.845e-3),
    (2.5, 2.378e-3),
    (3.0, 2.961e-3),
    (3.5, 3.596e-3),
    (4.0, 4.283e-3),
    (4.5, 5.027e-3),
    (5.0, 5.825e-3),
    (5.5, 6.678e-3),
    (6.0, 7.585e-3),
)
ENERGIES, MASS_RANGES = zip(*RANGE_TABLE)
REFERENCE_MEV = (5.155, 5.486, 5.805)
CHANNELS = 1024
MEV_PER_CHANNEL = 0.006
LINE_RATE_HZ = 25.0
DETECTOR_SIGMA_MEV = 0.012
DETECTOR_OUTPUT = "alpha_detector"
FOIL_SPEC_UM = (1.0, 2.0)


def normalize_settings(batch: Mapping[str, float]) -> Mapping[str, float]:
    """Adapt exact legacy live commands; archived thickness is never converted."""
    if "foil_um" not in batch:
        return batch
    if "foil_spec_um" in batch or "foil_count" in batch:
        raise ValueError("foil_um 与 foil_spec_um/foil_count 不能在同一批设置中混用，箔厚含义有歧义。")
    thickness = batch["foil_um"]
    if (isinstance(thickness, bool) or not isinstance(thickness, (int, float))
            or not math.isfinite(thickness) or not 0 <= thickness <= 40
            or int(thickness) != thickness):
        raise ValueError(
            "旧实时 foil_um 仅兼容 0–40 µm 的整数厚度；请迁移为 foil_spec_um=1 与 foil_count。"
            "2.5 µm 等历史厚度应直接读取原档案，不要用新实时设置重建。"
        )
    return {**{key: value for key, value in batch.items() if key != "foil_um"},
            "foil_spec_um": 1.0, "foil_count": int(thickness)}


def configured_foil(settings: Mapping[str, float]) -> AluminumFoil:
    """A stack of identical aluminium sheets; Session has validated the settings."""
    return AluminumFoil(settings["foil_spec_um"] * settings["foil_count"] / 1000)


def _interpolate(value: float, axis: tuple, values: tuple) -> float:
    """Linear interpolation on a strictly increasing finite tabulation."""
    if not axis[0] <= value <= axis[-1]:
        raise ValueError("value outside the aluminium range table")
    i = bisect_left(axis, value)
    if axis[i] == value:
        return values[i]
    weight = (value - axis[i - 1]) / (axis[i] - axis[i - 1])
    return values[i - 1] + weight * (values[i] - values[i - 1])


def transmitted_energy(incident_mev: float, foil: AluminumFoil) -> float:
    """CSDA residual energy for 0–6 MeV at normal incidence; 0 means stopped.

    The public helper rejects energies outside its tabulation rather than
    extrapolating. Foil thickness is supplied in mm through AluminumFoil.
    """
    incident_range = _interpolate(incident_mev, ENERGIES, MASS_RANGES)
    residual_range = max(0.0, incident_range - foil.areal_density_g_cm2)
    return _interpolate(residual_range, MASS_RANGES, ENERGIES)


def measure(settings: Mapping[str, float], start_s: float, end_s: float, rng: Random):
    """Sample one Session exposure into a channel histogram at fixed geometry."""
    counts = [0] * CHANNELS
    if not settings["source_present"]:
        return {DETECTOR_OUTPUT: counts}
    foil = configured_foil(settings)
    for energy in REFERENCE_MEV:
        residual_mev = transmitted_energy(energy, foil)
        if residual_mev == 0:
            continue
        arrivals = poisson(LINE_RATE_HZ * (end_s - start_s), rng)
        for _ in range(arrivals):
            pulse_mev = rng.gauss(residual_mev, DETECTOR_SIGMA_MEV)
            channel = math.floor(pulse_mev / MEV_PER_CHANNEL + 0.5)
            if pulse_mev > 0 and 0 <= channel < CHANNELS:
                counts[channel] += 1
    return {DETECTOR_OUTPUT: counts}


EXPERIMENT = Experiment(
    id="alpha",
    title="α 粒子在铝箔中的能量损失",
    description="采集无箔三峰参考谱，建立能量刻度；增加铝箔厚度后比较峰位。",
    parameters=(
        Parameter("source_present", "源座", "", 1, 0, 1, integer=True,
                  options=((0, "空源座"), (1, "α 三峰参考源"))),
        Parameter("foil_spec_um", "Al 单片厚度", "µm/片", 1.0, 1.0, 2.0,
                  options=((1.0, "Al 1 µm/片"), (2.0, "Al 2 µm/片"))),
        Parameter("foil_count", "铝箔片数", "片", 0, 0, 40, integer=True),
    ),
    devices=(Device("mca", "spectrum", "α 多道谱仪", channels=CHANNELS, input=DETECTOR_OUTPUT),),
    model=measure,
    question="α 粒子穿过铝箔后，谱峰能量怎样随箔厚变化？",
    guide=(
        "放入 α 三峰参考源，片数设为 0。分别打开硅探测器输出与多道谱仪采集门，采集无箔参考谱。"
        "教学源三条参考线的能量依次为 5.155、5.486 和 5.805 MeV。",
        "用 ROI 分别圈住低能和高能两个孤立峰，以实测峰心和对应参考能量建立两点刻度。"
        "用中间峰检验刻度，再保留这份参考谱。",
        "选择 Al 单片规格并增加片数，用总厚度等于单片厚度乘片数核对工况；与无箔谱比较同一条线的峰心。"
        "接近射程时谱线可能消失，此时记录峰区计数及实际曝光。",
    ),
    components=(
        Component("source", "source", "α 源座", "固定几何下可放入三峰参考源或移空源座；模型无本底，空源无源峰。",
                  ("source_present",), illustration="source"),
        Component("foil", "foil", "铝箔架", "装入同规格 Al 薄片，0 片表示空箔架；总厚度为单片厚度乘片数，独立于源座状态。",
                  ("foil_spec_um", "foil_count"), illustration="foil"),
        Component("detector", "detector", "硅探测器", "穿透铝箔的粒子产生脉冲，脉冲幅度反映沉积能量。",
                  illustration="silicon", output=DETECTOR_OUTPUT),
        Component("mca", "instrument", "多道谱仪", "按脉冲幅度分道，累计各道计数。", device="mca", illustration="mca"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 α 粒子"),
        Connection("foil", "detector", "particle", "透射 α 粒子"),
        Connection("detector", "mca", "signal", "幅度脉冲"),
    ),
    outputs=(SignalOutput(DETECTOR_OUTPUT, "硅探测器幅度输出", channels=CHANNELS,
                          response="固定几何及效率已计入每线25 s⁻¹；含12 keV标准差响应及0.006 MeV/道量化，无本底"),),
    normalize_settings=normalize_settings,
)
