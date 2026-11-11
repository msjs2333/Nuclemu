"""Alpha energy loss in aluminium, observed with a silicon spectrometer."""

import math
from bisect import bisect_left
from random import Random
from typing import Mapping

from nuclemu.core import Component, Connection, Device, Experiment, Parameter
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
    foil = AluminumFoil(settings["foil_um"] / 1000)
    counts = [0] * CHANNELS
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
    return {"mca": counts}


EXPERIMENT = Experiment(
    id="alpha",
    title="α 粒子在铝箔中的能量损失",
    description="采集无箔三峰参考谱，建立能量刻度；增加铝箔厚度后比较峰位。",
    parameters=(Parameter("foil_um", "铝箔厚度", "µm", 0.0, 0.0, 40.0),),
    devices=(Device("mca", "spectrum", "α 多道谱仪", channels=CHANNELS),),
    model=measure,
    question="α 粒子穿过铝箔后，谱峰能量怎样随箔厚变化？",
    guide=(
        "先将铝箔厚度调为 0 µm，打开多道谱仪采集无箔参考谱。"
        "教学源三条参考线的能量依次为 5.155、5.486 和 5.805 MeV。",
        "用 ROI 分别圈住低能和高能两个孤立峰，以实测峰心和对应参考能量建立两点刻度。"
        "用中间峰检验刻度，再保留这份参考谱。",
        "增加箔厚并重新采谱，与无箔谱比较同一条线的峰心。"
        "接近射程时谱线可能消失，此时记录峰区计数及实际曝光。",
    ),
    components=(
        Component("source", "source", "α 参考源", "固定源座发出三条已知能量的 α 谱线。", illustration="source"),
        Component("foil", "foil", "铝箔架", "改变法向入射粒子穿过的铝箔厚度。", ("foil_um",), illustration="foil"),
        Component("detector", "detector", "硅探测器", "穿透铝箔的粒子产生脉冲，脉冲幅度反映沉积能量。",
                  device="mca", illustration="silicon"),
        Component("mca", "instrument", "多道谱仪", "按脉冲幅度分道，累计各道计数。", device="mca", illustration="mca"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 α 粒子"),
        Connection("foil", "detector", "particle", "透射 α 粒子"),
        Connection("detector", "mca", "signal", "幅度脉冲"),
    ),
)
