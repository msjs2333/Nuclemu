"""Transmission counting with a fixed beta source geometry and aluminium foils."""

from collections.abc import Mapping
from dataclasses import replace
from random import Random

from nuclemu.core import Component, Connection, Device, Experiment, Parameter, SignalOutput
from nuclemu.physics import AluminumFoil, poisson


FOIL_THICKNESS_MM = 0.10
DETECTOR_OUTPUT = "beta_detector"
DETECTOR_OUTPUT_B = "beta_detector_b"
HALF_VALUE_AREAL_DENSITY_G_CM2 = 0.112
UNATTENUATED_SIGNAL_CPS = 100.0
BACKGROUND_CPS = 2.0
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
    transmission = 2.0 ** (-foil.areal_density_g_cm2 / HALF_VALUE_AREAL_DENSITY_G_CM2)
    unattenuated = UNATTENUATED_SIGNAL_CPS if settings["source_present"] else 0.0
    signal = unattenuated * transmission
    return {"areal_density_g_cm2": foil.areal_density_g_cm2,
            "transmission": transmission, "unattenuated_signal_cps": unattenuated,
            "transmitted_signal_cps": signal, "background_cps": BACKGROUND_CPS,
            "detector_cps": signal + BACKGROUND_CPS}


def particle_flow(settings: Mapping[str, int | float]) -> dict:
    """Model conditions for a qualitative display, never another acquisition."""
    rates = expected_rates(settings)
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
    mean = expected_rates(settings)['detector_cps'] * (end_s - start_s)
    return {DETECTOR_OUTPUT: (poisson(mean, rng),)}


def restore_definition(saved):
    """Recognize only this course's former one-output counter bindings."""
    if saved.get('id') != 'beta':
        return EXPERIMENT
    outputs = saved.get('outputs', ())
    devices = saved.get('devices', ())
    parameters = {p['key']: p for p in saved.get('parameters', ())}
    if (len(outputs) != 1 or outputs[0].get('id') != DETECTOR_OUTPUT
            or outputs[0].get('response') not in _LEGACY_SHARED_RESPONSES
            or outputs[0].get('channels', 1) != 1
            or outputs[0].get('unit', 'count') != 'count'
            or outputs[0].get('time_unit', 's') != 's'
            or not devices or len({d['id'] for d in devices}) != len(devices)
            or any(d['id'] not in ('counter', 'counter_b') or d.get('kind') != 'counter'
                   or d.get('channels') != 1 or d.get('input') != DETECTOR_OUTPUT for d in devices)
            or set(parameters) not in ({'source_present', 'foil_count'},
                                       {'source_present', 'foil_count', 'foil_spec_um'})):
        return EXPERIMENT
    for p in EXPERIMENT.parameters:
        if p.key in parameters and (parameters[p.key].get('minimum'), parameters[p.key].get('maximum')) != (p.minimum, p.maximum):
            return EXPERIMENT
    ids = tuple(d['id'] for d in devices)
    primary = 'counter' if 'counter' in ids else ids[0]
    parts = tuple(replace(p, parameters=tuple(key for key in p.parameters if key in parameters),
                          device=primary if p.kind == 'instrument' else p.device,
                          devices=ids if p.kind == 'instrument' else p.devices,
                          outputs=() if p.output else p.outputs)
                  for p in EXPERIMENT.components)
    return replace(EXPERIMENT, title='β 射线吸收（历史共享输入）',
                   description='保留文件的共享脉冲观测；继续测量沿用原共享输入模式。',
                   parameters=tuple(replace(p, default=parameters[p.key]['default'])
                                    for p in EXPERIMENT.parameters if p.key in parameters),
                   devices=tuple(replace(next(d for d in EXPERIMENT.devices if d.id == old['id']),
                                         input=DETECTOR_OUTPUT) for old in devices),
                   outputs=(replace(EXPERIMENT.outputs[0], label=outputs[0]['label'],
                                    response=outputs[0].get('response', '')),),
                   components=parts, model=sample_shared_counts,
                   restore_definition=None,
                   guide=('本文件 A、B 接收同一批脉冲，按原共享输入模型继续；新课采用两组独立重复观测。',))


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
                         "固定几何、阈值、探测效率及源窗已计入有效吸收计数率；含环境本底。"
                         "同工况虚拟重复观测 A，独立泊松抽样，不是同脉冲分接。"),
             SignalOutput(DETECTOR_OUTPUT_B, "β 重复观测 B", response=
                         "与 A 使用相同平均响应的独立重复观测；不再乘效率。")),
    restore_definition=restore_definition,
    particle_flow=particle_flow,
    short_code="BABS",
    question="增加铝箔片数后，扣除本底的 β 计数率怎样变化？",
    guide=(
        "在装置源座选择空源座，开启探测器输出，用计数器记录本底计数和实际曝光，例如 60 s。",
        "放入 β 源。先测无箔读数，再分别加入 4、8、16 片铝箔测量；默认每片厚 100 µm。"
        "不同厚度可设不同采集时间。",
        "同一计数器的 A、B 两窗可分别设置窗长，共用开始、暂停与继续。将 A 设为 1 s、B 设为 5 s，"
        "比较各窗的实际曝光与整数计数；暂停后继续，核对读数沿本轮累计。",
        "A、B 表示同一工况下两组独立的虚拟重复观测，不是同一批电脉冲的分接；允许偶然取得相同计数。",
        "保存并导出本底和样品的逐窗记录，在本地按各自实际曝光求计数率、扣除本底并估计不确定度，"
        "比较不同面密度下的透射变化。",
    ),
    components=(
        Component("source", "source", "β 源座", "空源座仍可测环境本底；放入 β 源测量透射信号。", ("source_present",), illustration="source"),
        Component("foil", "foil", "箔架", "箔架把薄箔固定在源与探测器之间。装入铝箔后，"
                  "可观察材料厚度改变时透射计数率的变化。", ("foil_spec_um", "foil_count"), illustration="foil"),
        Component("detector", "detector", "β 探测器", "在固定几何下记录到达探测器且通过甄别的脉冲。",
                  output=DETECTOR_OUTPUT, outputs=(DETECTOR_OUTPUT, DETECTOR_OUTPUT_B), illustration="beta-probe"),
        Component("counter", "instrument", "计数器", "计数器在设定的曝光窗内累计探测脉冲。"
                  "本课在同一面板显示 A、B 两窗的逐窗计数和实际曝光，分别设窗长并共用启停。",
                  device="counter", devices=("counter", "counter_b"), illustration="counter"),
    ),
    connections=(
        Connection("source", "foil", "particle", "入射 β 粒子"),
        Connection("foil", "detector", "particle", "透射 β 粒子"),
        Connection("detector", "counter", "signal", "计数脉冲"),
    ),
)
