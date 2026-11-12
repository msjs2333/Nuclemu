"""Course background examples: python -m examples.beta_background."""

from copy import deepcopy
import json

from examples.beta_windows import background_comparison, saved_windows
from nuclemu.core import Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT
from nuclemu.workbench import Workbench


def zero_sample():
    """Actual short exposures give a valid zero sample and negative net rate."""
    bench = Workbench(definitions={"beta": EXPERIMENT}, seed=0)
    bench.set_output(DETECTOR_OUTPUT, True)
    for source in (0, 1):
        bench.configure({"source_present": source, "foil_count": 24})
        bench.start(.1, device="counter")
        bench.advance(.1)
        bench.snapshot(device="counter")
        bench.clear(device="counter")
    bench.set_output(DETECTOR_OUTPUT, False)
    raw = deepcopy(bench.product())
    saved = saved_windows(bench.session)
    bench.select(1)
    uncorrected = bench.readout()
    bench.set_background(0)
    corrected = bench.readout()
    assert bench.product() == raw and saved_windows(bench.session) == saved
    return {"seed": 0, "background_segment": 0, "sample_segment": 1,
            "uncorrected": uncorrected, "corrected": corrected,
            "uncertainty_interpretation": "独立泊松计数代入传播的近似标准不确定度，不是精确置信区间",
            "saved_windows": saved, "product": raw}


def overlapping_snapshots():
    """Annotated non-independent case, not an automatic provenance classifier."""
    s = Session(EXPERIMENT, seed=42)
    s.set('source_present', 1)
    s.set_output(DETECTOR_OUTPUT, True)
    s.start(5, device="counter")
    s.advance(3)
    first = s.snapshot("counter")
    s.advance(2)
    second = s.snapshot("counter")
    s.set_output(DETECTOR_OUTPUT, False)
    assert first.acquisition == second.acquisition
    assert first.exposure_s == 3 and second.exposure_s == 5
    return {"seed": 42, "saved_windows": saved_windows(s), "shared_exposure_s": 3,
            "independent_poisson_subtraction": False,
            "reason": "同轮第二份累计快照包含第一份的全部曝光和计数，不能当作独立本底。"}


if __name__ == "__main__":
    print(json.dumps({"unequal_exposure": background_comparison(),
                      "zero_sample": zero_sample(),
                      "overlap": overlapping_snapshots()}, ensure_ascii=False, indent=2))
