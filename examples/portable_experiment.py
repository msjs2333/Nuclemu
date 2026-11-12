"""Run python -m examples.portable_experiment [--directory OUTPUT_DIRECTORY]."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import (bind_calibration, cache_calibration, capture_session, export_item,
    import_item, load_item, load_package, reopen_session, save_package)
from nuclemu.results import Calibration, roi_centroid


def run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    experiment = discover()["alpha"]
    session = Session(experiment, seed=187)
    session.set_output("alpha_detector", True)
    session.start(5, device="mca")
    session.advance(3)
    first = session.snapshot("mca")
    session.advance(2)
    second = session.snapshot("mca")
    doc = capture_session(session)
    ids = [i["id"] for i in doc["items"]]
    doc["items"][0]["title"] = "Reference at 3 seconds"
    doc["items"][1]["title"] = "Reference at 5 seconds"
    c1, c2 = roi_centroid(first.counts, 845, 875), roi_centroid(first.counts, 950, 985)
    calibration = Calibration("alpha", "mca", 1024, c1, 5.155, c2, 5.805)
    calibration_id = cache_calibration(doc, calibration)
    for identity in ids:
        bind_calibration(doc, identity, calibration_id)
    doc["analysis"] = {"mca": dict(roi=[845, 875], reference=ids[0], selected=ids[1], background=None)}
    package = directory / "alpha.nuclemu"
    save_package(package, doc)
    for format in ("csv", "json"):
        (directory / f"reference-3s.{format}").write_bytes(export_item(doc, ids[0], format))
    offline = directory / "offline-copy"
    offline.mkdir(exist_ok=True)
    (offline / package.name).write_bytes(package.read_bytes())
    loaded = load_package(offline / package.name)
    assert loaded == doc
    fresh = reopen_session(loaded, experiment)
    assert fresh.instrument("mca").exposure_s == 0 and not fresh.clock_running
    fresh.set_output("alpha_detector", True)
    fresh.start(1, device="mca")
    fresh.advance(1)
    third = fresh.snapshot("mca")
    assert third.acquisition == 2 and third.exposure_s == 1
    continued = capture_session(fresh, loaded)
    assert continued["items"][0] == doc["items"][0]
    target = capture_session(Session(experiment))
    imported = import_item(target, load_item(directory / "reference-3s.csv"), ids[0])
    assert imported != ids[0] and len(target["items"]) == 2
    save_package(directory / "imported.nuclemu", target)
    print(f"saved snapshots: {sum(first.counts)}/3 s, {sum(second.counts)}/5 s; same round {first.acquisition}")
    print(f"reopened new round: {third.acquisition}, exposure {third.exposure_s:g} s; old 3 s snapshot unchanged")
    print(f"portable files: {directory}")
    return doc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory")
    args = parser.parse_args()
    if args.directory:
        run(args.directory)
    else:
        with TemporaryDirectory() as directory:
            run(directory)
