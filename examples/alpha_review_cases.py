"""Write actual spectra for calibration and mixed-condition review.

Run ``python -m examples.alpha_review_cases OUTPUT_DIRECTORY``. The output
directory is explicit so generated measurements need not enter the repository.
All spectra are acquired by the same public Session used by the laboratory.
The statistical_flows field preserves physical reference metadata; it is not
a conversion scale for visual fan beams, background dots or their colours.
"""

import argparse
import json
from pathlib import Path

from nuclemu.core import Session
from nuclemu.experiments.alpha import DETECTOR_OUTPUT, EXPERIMENT, particle_flow
from nuclemu.exchange import bind_calibration, cache_calibration, capture_session, save_item, save_package
from nuclemu.results import Calibration, roi_centroid


def acquire(*, mixed=False, seed=187):
    session = Session(EXPERIMENT, seed=seed)
    session.configure({"source_present": 1, "foil_spec_um": 1, "foil_count": 0})
    session.set_output(DETECTOR_OUTPUT, True)
    session.start(3, device="mca")
    if mixed:
        session.advance(2)
        session.set("foil_count", 1)
        session.advance(1)
    else:
        session.advance(3)
    snapshot = session.snapshot("mca")
    session.set_output(DETECTOR_OUTPUT, False)
    return session, snapshot


def write_cases(directory, seed=187):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name, maximum_mev, mixed in (("history-3mev", 3, False),
                                     ("current-6mev", 6, False),
                                     ("mixed-2s-plus-1s", 6, True)):
        session, snapshot = acquire(mixed=mixed, seed=seed)
        doc = capture_session(session)
        measurement = next(item for item in doc["items"] if item["kind"] == "measurement")
        measurement["title"] = name
        calibration = Calibration("alpha", "mca", 1024, 0, 0, 1000, maximum_mev)
        identity = cache_calibration(doc, calibration, title=f"1000 channels = {maximum_mev} MeV")
        bind_calibration(doc, measurement["id"], identity)
        doc["analysis"] = {"mca": dict(selected=measurement["id"], reference=None,
                                       background=None, roi=[900, 929], energy_axis=True, rate_axis=False)}
        save_package(directory / (name + ".nuclemu"), doc)
        save_item(directory / (name + ".json"), doc, measurement["id"])
        save_item(directory / (name + "-calibration.json"), doc, identity)
        center = roi_centroid(snapshot.counts, 900, 929)
        summaries.append(dict(name=name, seed=seed, total_counts=sum(snapshot.counts),
            exposure_s=snapshot.exposure_s, roi=[900, 929],
            roi_counts=sum(snapshot.counts[900:930]), centroid_channel=center,
            energy_MeV=None if center is None else calibration.energy(center),
            calibration=calibration.document(),
            segments=[dict(settings=dict(segment.settings), exposure_s=segment.exposure_s,
                           total_counts=sum(segment.readings["mca"])) for segment in snapshot.segments]))
    flows = [dict(settings=dict(source_present=source, foil_spec_um=1, foil_count=count),
                  flow=particle_flow(dict(source_present=source, foil_spec_um=1, foil_count=count)))
             for source, count in ((0, 0), (1, 0), (1, 5), (1, 25), (1, 30))]
    result = dict(protocol=f"seed{seed}; normal 3 s gate; mixed case changes from 0 to 1 um at 2 s",
                  cases=summaries, statistical_flows=flows)
    (directory / "cases.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_cases(args.directory), ensure_ascii=False, indent=2))
