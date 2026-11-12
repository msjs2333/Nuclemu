"""Run with python -m examples.split_signal from the repository root."""

import json

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.results import MeasurementView


def run():
    definition = discover(["examples/courses"])["split-signal"]
    session = Session(definition, seed=187)
    session.set_output("detector", True)
    session.start(10, device="a")
    session.start(10, device="b")
    session.advance(3)
    session.set_output("detector", False)
    session.advance(4)
    session.set_output("detector", True)
    session.advance(3)
    session.set_output("detector", False)
    session.advance(100)  # All demands have stopped: laboratory time stays at 10.
    assert session.time_s == 10
    assert session.instrument("a").exposure_s == session.instrument("b").exposure_s == 10
    return MeasurementView(session).product()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
