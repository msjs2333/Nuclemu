"""Run with python -m examples.acquisition_rounds from the repository root."""

from math import floor

from nuclemu.core import Device, Experiment, Session, SignalOutput


def counted_windows(settings, start, end, rng):
    counts = (42, 47, 18)
    def prefix(t):
        index = min(floor(t), len(counts))
        return sum(counts[:index]) + (round(counts[index] * (t-index)) if index < len(counts) else 0)
    return {"detector": (prefix(end) - prefix(start),)}


def pulses(settings, start, end, rng):
    return {"detector": (floor(end*10) - floor(start*10),)}


def session(model):
    experiment = Experiment("round-example", "采集轮次示例", "确定性输入验收。", (),
                            (Device("a", "counter", "A", input="detector"),
                             Device("b", "counter", "B", input="detector")), model,
                            outputs=(SignalOutput("detector", "脉冲输出"),))
    result = Session(experiment)
    result.set_output("detector", True)
    return result


if __name__ == "__main__":
    limited = session(counted_windows)
    limited.start(device="a", count_limit=100)
    limited.advance(5)
    state = limited.instrument("a")
    assert (state.counts, state.exposure_s, state.stop_reason) == ((107,), 3, "count_limit")
    print(f"count limit: {state.counts[0]} counts / {state.exposure_s:g} s")

    lab = session(pulses)
    lab.start(device="a")
    lab.advance(2.4)
    lab.stop(device="a")
    lab.start(device="a")
    lab.advance(.6)
    lab.stop(device="a")
    state = lab.instrument("a")
    assert (state.acquisition, state.counts, state.exposure_s) == (1, (30,), 3)
    print(f"pause and resume: round {state.acquisition}, {state.counts[0]} counts / {state.exposure_s:g} s")

    lab.clear(device="a")
    lab.start(10, device="a")
    lab.start(device="b")
    lab.advance(3)
    request = lab.begin_clear("a")
    lab.advance(2)
    lab.finish_clear("a", request.token, "save")
    assert lab.snapshots[-1].exposure_s == 3
    assert lab.instrument("b").exposure_s == 5
    assert lab.instrument("a").exposure_s == 0
    print("clear A: saved 3 s; B continues at 5 s")
