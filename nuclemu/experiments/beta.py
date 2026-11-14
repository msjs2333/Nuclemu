"""Transmission counting with a fixed beta source geometry and aluminium foils."""

from collections.abc import Mapping
from dataclasses import replace
from math import exp
from random import Random

from nuclemu.core import Component, Connection, Device, Experiment, Parameter, SignalOutput
from nuclemu.physics import AluminumFoil, poisson


FOIL_THICKNESS_MM = 0.10
DETECTOR_OUTPUT = "beta_detector"
DETECTOR_OUTPUT_B = "beta_detector_b"
BACKGROUND_CPS = 50.0
RESPONSE_COMPONENTS = ((10000.0, 39.5), (1600.0, 2.2))  # cps, cm²/g
UNATTENUATED_SIGNAL_CPS = sum(amplitude for amplitude, _ in RESPONSE_COMPONENTS)
CALIBRATED_AREAL_DENSITY_G_CM2 = 0.4
LEGACY_INDEPENDENT_RESPONSES = (
    "固定几何、阈值、探测效率及源窗已计入有效吸收计数率；含环境本底。"
    "同工况虚拟重复观测 A，独立泊松抽样，不是同脉冲分接。",
    "与 A 使用相同平均响应的独立重复观测；不再乘效率。",
)
LEGACY_SHARED_RESPONSE = (
    "固定几何、阈值、探测效率及源窗已计入有效吸收计数率；含环境本底。"
    "同一计数器的两窗理想无损分接，不再乘效率。"
)
_LEGACY_SHARED_RESPONSES = (
    LEGACY_SHARED_RESPONSE,
    "固定几何、阈值、探测效率及源窗已计入有效吸收计数率；含环境本底。"
    "两台计数器理想无损分接，不再乘效率。",
)


def expected_rates(settings: Mapping[str, int | float]) -> dict[str, float]:
    """Fixed-geometry mean response, independent of the RNG and output switch.

    The unattenuated signal is an effective detected rate, not source activity
    or an absolute particle flux. These model means are not a count of the
    illustrative dots on the apparatus; they describe no particle track.
    Settings have already been validated by the experiment boundary.
    """
    foil = AluminumFoil(settings["foil_count"] *
                        settings.get("foil_spec_um", FOIL_THICKNESS_MM * 1000) / 1000)
    transmitted = sum(amplitude * exp(-coefficient * foil.areal_density_g_cm2)
                      for amplitude, coefficient in RESPONSE_COMPONENTS)
    transmission = transmitted / UNATTENUATED_SIGNAL_CPS
    unattenuated = UNATTENUATED_SIGNAL_CPS if settings["source_present"] else 0.0
    signal = unattenuated * transmission
    return {"areal_density_g_cm2": foil.areal_density_g_cm2,
            "transmission": transmission, "unattenuated_signal_cps": unattenuated,
            "transmitted_signal_cps": signal, "background_cps": BACKGROUND_CPS,
            "detector_cps": signal + BACKGROUND_CPS}


def _previous_rates(settings):
    """The saved single-exponential response must not follow current constants."""
    mass = AluminumFoil(settings['foil_count'] * settings.get('foil_spec_um', 100) / 1000).areal_density_g_cm2
    transmission = 2 ** (-mass / .112)
    incident = 100.0 if settings['source_present'] else 0.0
    return dict(areal_density_g_cm2=mass, transmission=transmission,
                unattenuated_signal_cps=incident, transmitted_signal_cps=incident*transmission,
                background_cps=2.0, detector_cps=2.0+incident*transmission)


def particle_flow(settings: Mapping[str, int | float]) -> dict:
    """Model conditions for a qualitative display, never another acquisition."""
    return _particle_flow(settings, expected_rates(settings))


def _previous_flow(settings):
    return _particle_flow(settings, _previous_rates(settings))


def _particle_flow(settings, rates):
    return {"kind": "beta_effective_transmission", "material": "Al",
            "thickness_um": settings["foil_count"] * settings.get("foil_spec_um", 100),
            "areal_density_g_cm2": rates["areal_density_g_cm2"],
            "incident_rate_s": rates["unattenuated_signal_cps"],
            "transmitted_rate_s": rates["transmitted_signal_cps"],
            "background_rate_s": rates["background_cps"],
            "transmission": rates["transmission"]}


def sample_counts(
    settings: Mapping[str, int | float], start_s: float, end_s: float, rng: Random
) -> dict[str, tuple[int, ...]]:
    rate = expected_rates(settings)["detector_cps"]
    mean = rate * (end_s - start_s)
    return {DETECTOR_OUTPUT: (poisson(mean, rng),),
            DETECTOR_OUTPUT_B: (poisson(mean, rng),)}


def sample_shared_counts(settings, start_s, end_s, rng):
    """Historical ideal pulse split, retained when continuing an old package."""
    mean = _previous_rates(settings)['detector_cps'] * (end_s - start_s)
    return {DETECTOR_OUTPUT: (poisson(mean, rng),)}


def _previous_independent_counts(settings, start_s, end_s, rng):
    mean = _previous_rates(settings)['detector_cps'] * (end_s - start_s)
    return {DETECTOR_OUTPUT: (poisson(mean, rng),), DETECTOR_OUTPUT_B: (poisson(mean, rng),)}


def restore_definition(saved):
    """Select recognized saved responses without changing their counting model."""
    if saved.get('id') != 'beta':
        return NotImplemented
    outputs = saved.get('outputs', ())
    devices = saved.get('devices', ())
    parameters = {p['key']: p for p in saved.get('parameters', ())}
    output_map = {o['id']: o for o in outputs}
    shared = (len(outputs) == 1 and outputs[0].get('id') == DETECTOR_OUTPUT
              and outputs[0].get('response') in _LEGACY_SHARED_RESPONSES)
    independent = (len(outputs) == 2 and set(output_map) == {DETECTOR_OUTPUT, DETECTOR_OUTPUT_B}
                   and all(output_map[key].get('response') == response for key, response in
                           zip((DETECTOR_OUTPUT, DETECTOR_OUTPUT_B), LEGACY_INDEPENDENT_RESPONSES)))
    if (not (shared or independent)
            or any(o.get('channels', 1) != 1 or o.get('unit', 'count') != 'count'
                   or o.get('time_unit', 's') != 's' for o in outputs)
            or not devices or len({d['id'] for d in devices}) != len(devices)
            or any(d['id'] not in ('counter', 'counter_b') or d.get('kind') != 'counter'
                   or d.get('channels') != 1 or d.get('input') !=
                   (DETECTOR_OUTPUT_B if independent and d['id'] == 'counter_b' else DETECTOR_OUTPUT)
                   for d in devices)
            or set(parameters) not in ({'source_present', 'foil_count'},
                                       {'source_present', 'foil_count', 'foil_spec_um'})):
        return NotImplemented
    for p in EXPERIMENT.parameters:
        if p.key in parameters and (parameters[p.key].get('minimum'), parameters[p.key].get('maximum')) != (p.minimum, p.maximum):
            return NotImplemented
    ids = tuple(d['id'] for d in devices)
    primary = 'counter' if 'counter' in ids else ids[0]
    parts = tuple(replace(p, parameters=tuple(key for key in p.parameters if key in parameters),
                          device=primary if p.kind == 'instrument' else p.device,
                          devices=ids if p.kind == 'instrument' else p.devices,
                          outputs=(() if shared else (DETECTOR_OUTPUT, DETECTOR_OUTPUT_B)) if p.output else p.outputs)
                  for p in EXPERIMENT.components)
    description = ('保留文件的共享脉冲观测；继续测量沿用原共享输入模式。' if shared else
                   '保留文件的独立重复观测；继续测量沿用原单指数响应。')
    return replace(EXPERIMENT, title='β 射线吸收（历史共享输入）' if shared else 'β 射线吸收（历史响应）',
                   description=description + '原响应本底 2 s⁻¹、无箔净率 100 s⁻¹、半值面密度 0.112 g/cm²。',
                   parameters=tuple(replace(p, default=parameters[p.key]['default'])
                                    for p in EXPERIMENT.parameters if p.key in parameters),
                   devices=tuple(replace(next(d for d in EXPERIMENT.devices if d.id == old['id']),
                                         input=old['input']) for old in devices),
                   outputs=tuple(replace(next(o for o in EXPERIMENT.outputs if o.id == old['id']),
                                         label=old['label'], response=old['response']) for old in outputs),
                   components=parts, model=sample_shared_counts if shared else _previous_independent_counts,
                   particle_flow=_previous_flow,
                   restore_definition=None,
                   guide=(description,))


EXPERIMENT = Experiment(
    id="beta",
    title="β 射线吸收",
    description="测量本底，在相同几何下加入铝箔，比较单位时间内记录的净计数。"
                "A、B 为同工况的独立虚拟重复观测。",
    parameters=(
        Parameter("source_present", "源座", "", 0, 0, 1, integer=True,
                  options=((0, "空源座"), (1, "β 源"))),
        Parameter("foil_count", "铝箔片数", "片", 0, 0, 24, integer=True),
        Parameter("foil_spec_um", "铝箔单片规格", "µm/片", 100, 50, 100, integer=True,
                  options=((50, "50 µm/片"), (100, "100 µm/片"))),
    ),
    devices=(Device("counter", "counter", "窗 A",
                    background_conditions={"source_present": 0}, input=DETECTOR_OUTPUT),
             Device("counter_b", "counter", "窗 B",
                    background_conditions={"source_present": 0}, input=DETECTOR_OUTPUT_B)),
    model=sample_counts,
    outputs=(SignalOutput(DETECTOR_OUTPUT, "β 重复观测 A", response=
                         "Al 固定几何有效响应：R=50+source×(10000exp(-39.5m)+1600exp(-2.2m)) s⁻¹；"
                         "m 单位 g/cm²，课程校核区间 0–0.4，扩展至 0.648 属教学外推；A 独立泊松重复。"),
             SignalOutput(DETECTOR_OUTPUT_B, "β 重复观测 B", response=
                         "与 A 相同的双成分有效平均响应；B 独立泊松重复，含独立本底涨落，不再乘效率。")),
    restore_definition=restore_definition,
    particle_flow=particle_flow,
    short_code="BABS",
    question="增加铝箔片数后，扣除本底的 β 计数率怎样变化？",
    guide=(
        "在装置源座选择空源座，开启探测器输出，用计数器记录本底计数和实际曝光，例如 30 s。",
        "放入 β 源。默认每片厚 100 µm，可测 0、1、2、4、8、12、14 片，每点例如 5 s。"
        "50 µm 两片与 100 µm 一片面密度相同。总面密度超过 0.4 g/cm² 时属于教学外推。",
        "同一计数器的 A、B 两窗可分别设置窗长，共用开始、暂停与继续。将 A 设为 1 s、B 设为 5 s，"
        "比较各窗的实际曝光与整数计数；暂停后继续，核对读数沿本轮累计。",
        "A、B 表示同一工况下两组独立的虚拟重复观测，不是同一批电脉冲的分接；允许偶然取得相同计数。",
        "保存并导出本底和样品的逐窗记录，在本地按各自实际曝光求计数率、扣除本底并估计不确定度，"
        "比较不同面密度下的透射变化。",
    ),
    components=(
        Component("source", "source", "β 源座", "放射性核素衰变可发射 β 粒子。本课源座与探测器的几何位置固定；"
                  "空源座用于测环境本底，放入 β 源后比较穿过铝箔的有效计数。", ("source_present",), illustration="source"),
        Component("foil", "foil", "箔架", "带电粒子穿过铝时会损失能量并发生散射。箔架把薄片固定在源与探测器之间；"
                  "本课改变规格和片数，以总面密度比较透射计数率。", ("foil_spec_um", "foil_count"), illustration="foil"),
        Component("detector", "detector", "β 探测器", "探测器把接收的有效辐射转换成可计数的电信号。"
                  "本课固定几何和甄别条件，输出开关控制送入计数器的信号，不改变源的状态。",
                  output=DETECTOR_OUTPUT, outputs=(DETECTOR_OUTPUT, DETECTOR_OUTPUT_B), illustration="beta-probe"),
        Component("counter", "instrument", "计数器", "计数器在采集门开启的实际曝光内累计离散计数。"
                  "本课同台 A、B 两窗表示同工况的独立虚拟重复观测，分别设窗长，整机共同启停与保存读数。",
                  device="counter", devices=("counter", "counter_b"), illustration="counter"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 β 粒子"),
        Connection("foil", "detector", "particle", "透射 β 粒子"),
        Connection("detector", "counter", "signal", "计数脉冲"),
    ),
)
