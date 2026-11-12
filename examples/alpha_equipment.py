"""Run with python -m examples.alpha_equipment from the repository root.

One continuous MCA exposure is segmented by four applied foil settings.
This is a model/interface reference, not a substitute for saved snapshots.
"""

import json

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.experiments.alpha import DETECTOR_OUTPUT, configured_foil
from nuclemu.results import Calibration, MeasurementView, roi_centroid


REGIONS = (
    ((845, 874), (900, 929), (952, 982)),
    ((703, 733), (764, 794), (824, 854)),
    ((349, 379), (434, 464), (514, 544)),
    ((0, 1023),),
)


def acquire_series(seed=187):
    session = Session(discover()["alpha"], seed=seed)
    session.set_output(DETECTOR_OUTPUT, True)
    session.start(240, device="mca")
    for count in (0, 5, 15, 30):
        session.configure({"source_present": 1, "foil_spec_um": 1, "foil_count": count})
        session.advance(60)
    session.set_output(DETECTOR_OUTPUT, False)
    session.advance(100)
    assert session.time_s == 240
    return MeasurementView(session).product()


def run(seed=187):
    product = acquire_series(seed)
    reference = product["segments"][0]["readings"]["mca"]
    low = roi_centroid(reference, *REGIONS[0][0])
    high = roi_centroid(reference, *REGIONS[0][2])
    calibration = Calibration("alpha", "mca", 1024, low, 5.155, high, 5.805)
    rows = []
    for segment, regions in zip(product["segments"], REGIONS):
        counts = segment["readings"]["mca"]
        foil = configured_foil(segment["settings"])
        peaks = []
        for first, last in regions:
            center = roi_centroid(counts, first, last)
            peaks.append(dict(roi=[first, last], counts=sum(counts[first:last + 1]),
                              centroid_channel=center,
                              energy_MeV=None if center is None else calibration.energy(center)))
        rows.append(dict(settings=segment["settings"], thickness_um=foil.thickness_mm * 1000,
                         areal_density_g_cm2=foil.areal_density_g_cm2,
                         exposure_s=segment["end_s"] - segment["start_s"],
                         total_counts=sum(counts), peaks=peaks))
    return dict(experiment="alpha", seed=seed, device="mca", input=DETECTOR_OUTPUT,
                protocol="one 240 s gate; apply 0/5/15/30 sheets at 0/60/120/180 s",
                calibration=calibration.document(), readings=rows)


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
