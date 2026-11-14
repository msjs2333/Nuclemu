"""Export and reopen known-input measurements, including foreign-time loading.

Run ``python -m examples.measurement_restore OUTPUT_DIRECTORY``. The periodic
input verifies acquisition boundaries; it is not a radioactive-source model.
"""

import json
from math import floor
from pathlib import Path
import sys

from nuclemu.core import Device, Experiment, Session, SignalOutput
from nuclemu.exchange import (capture_session, decode_measurement, export_item,
                              load_package, reopen_session, save_package)


def pulses(settings, start, end, rng):
    return {"out": (floor(end * 10) - floor(start * 10),)}


EXPERIMENT = Experiment("measurement-restore", "Known-input acquisition", "Ten periodic pulses per second.", (),
    (Device("a", "counter", "A", input="out"), Device("b", "counter", "B", input="out")),
    pulses, outputs=(SignalOutput("out", "Periodic input"),))


def session():
    result = Session(EXPERIMENT, seed=187)
    result.set_output("out", True)
    return result


def write_examples(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    evidence = {}
    for choice in ("cancel", "failure"):
        lab = session()
        lab.start_group(("a", "b"))
        lab.advance(3)
        request = lab.begin_clear("a")
        lab.advance(2.5)
        def fail(snapshot):
            raise OSError("Example cache failure")
        try:
            lab.finish_clear("a", request.token, "save" if choice == "failure" else "cancel", writer=fail)
        except OSError:
            if choice != "failure":
                raise
        lab.advance(.5)
        for device in ("a", "b"):
            lab.snapshot(device)
        path = directory / f"clear-{choice}.nuclemu"
        save_package(path, capture_session(lab))
        loaded = reopen_session(load_package(path), EXPERIMENT)
        evidence[choice] = [(item.device, item.counts, item.exposure_s) for item in loaded.snapshots]
        assert evidence[choice] == [("a", (35,), 3.5), ("b", (60,), 6)]

    source = session()
    source.advance(100)
    source.start(device="a")
    source.advance(3)
    source.snapshot("a")
    source.advance(2)
    doc = capture_session(source)
    save_package(directory / "source.nuclemu", doc)
    evidence["source"] = dict(round_exposure_s=doc["rounds"][0]["exposure_s"],
                               saved_exposure_s=source.snapshots[0].exposure_s)
    assert evidence["source"] == dict(round_exposure_s=5, saved_exposure_s=3)
    for format in ("json", "csv"):
        path = directory / f"source-a.{format}"
        path.write_bytes(export_item(doc, doc["items"][0]["id"], format))
        target = session()
        target.start(device="b")
        decoded = decode_measurement(path, EXPERIMENT, "a")
        target.load_measurement("a", decoded.snapshot)
        assert target.time_s == 0
        target.start(device="a")
        target.advance(1)
        target.snapshot("a")
        save_package(directory / f"loaded-{format}.nuclemu", capture_session(target))
        reopened = reopen_session(load_package(directory / f"loaded-{format}.nuclemu"), EXPERIMENT)
        item = reopened.snapshots[0]
        evidence[format] = dict(counts=item.counts, exposure_s=item.exposure_s, windows=len(item.windows),
                                original_start_s=item.segments[0].start_s, original_end_s=item.segments[0].end_s,
                                b_counts=target.instrument("b").counts, current_time_s=target.time_s)
        assert item.counts == (40,) and item.exposure_s == 4 and len(item.windows) == 4
        assert item.segments[0].start_s == 100 and item.segments[0].end_s == 103
        assert target.instrument("b").counts == (10,)
    (directory / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    print(json.dumps(write_examples(sys.argv[1]), ensure_ascii=False, indent=2))
