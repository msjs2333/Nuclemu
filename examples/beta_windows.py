"""Beta course timelines: python -m examples.beta_windows from the repository root."""

from copy import deepcopy
import json

from nuclemu.core import Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT
from nuclemu.results import MeasurementView
from nuclemu.workbench import Workbench


def counts(session, device):
    return sum(row.readings[device][0] for row in session.records if device in row.readings)


def saved_windows(session):
    return [{"id": s.id, "device": s.device, "acquisition": s.acquisition,
             "exposure_s": s.exposure_s, "counts": list(s.counts)} for s in session.snapshots]


def dual_windows(*, seed=42, reopen=True):
    """Legacy two-round example; numerical sums are not a course criterion."""
    session = Session(EXPERIMENT, seed=seed)
    session.set("source_present", 1)
    session.set("foil_count", 4)
    session.set_output(DETECTOR_OUTPUT, True)
    session.start(5, device="counter")
    session.start(10, device="counter_b")
    session.advance(5)
    first = counts(session, "counter")
    assert not session.instrument("counter").running
    assert session.instrument("counter_b").running
    session.snapshot("counter")
    if reopen:
        session.clear(device="counter")
        session.start(5, device="counter")
    session.advance(5)
    session.set_output(DETECTOR_OUTPUT, False)
    total = counts(session, "counter")
    long = counts(session, "counter_b")
    if reopen:
        session.snapshot("counter")
    else:
        assert total == first
    session.snapshot("counter_b")
    return {"seed": seed, "A_first_5s": first, "A_second_5s": total - first if reopen else None,
            "B_10s": long, "A_reopened": reopen,
            "saved_windows": saved_windows(session),
            "product": MeasurementView(session).product()}


def background_comparison(*, seed=42):
    """Switch independent background references without changing any raw readings."""
    bench = Workbench(definitions={"beta": EXPERIMENT}, seed=seed)
    bench.set_output(DETECTOR_OUTPUT, True)
    # Use only A here: sample/background have disjoint exposures on the same device.
    for source, foils, duration in ((0, 0, 19.5), (1, 4, 7.25), (0, 0, 9.25)):
        bench.configure({"source_present": source, "foil_count": foils})
        bench.start(duration, device="counter")
        bench.advance(duration)
        bench.snapshot(device="counter")
        bench.clear(device="counter")
    bench.set_output(DETECTOR_OUTPUT, False)
    original = deepcopy(bench.product())
    snapshots = saved_windows(bench.session)
    bench.select(1)
    results = []
    for reference in (0, 2):
        bench.set_background(reference)
        results.append({"background_segment": reference, **bench.readout()})
    assert bench.product() == original
    assert saved_windows(bench.session) == snapshots
    return {"seed": seed, "sample_segment": 1, "comparisons": results,
            "saved_windows": snapshots, "product": original}


if __name__ == "__main__":
    print(json.dumps({"dual_windows": dual_windows(), "A_stopped": dual_windows(reopen=False),
                      "backgrounds": background_comparison()}, ensure_ascii=False, indent=2))
