"""A single Poisson detector output connected to two ideal scalers."""

from nuclemu.core import Device, Experiment, Parameter, SignalOutput
from nuclemu.physics import poisson


def detector(settings, start, end, rng):
    return {"detector": (poisson(settings["rate"] * (end - start), rng),)}


EXPERIMENT = Experiment(
    "split-signal", "双计数器分接", "两台独立开门的计数器读取同一探测输出。",
    (Parameter("rate", "探测计数率", "1/s", 40, 0, 10000),),
    (Device("a", "counter", "计数器 A", input="detector"),
     Device("b", "counter", "计数器 B", input="detector")),
    detector,
    outputs=(SignalOutput("detector", "探测器输出", response="已包含探测效率；理想无损分接"),),
)
