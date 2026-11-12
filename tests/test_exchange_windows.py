"""Window files and fixed measured prefixes survive independent live sessions."""

from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from examples.beta_window_rows import acquire
from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.exchange import (capture_session, decode_measurement, export_item, load_item,
    load_package, package_bytes, reopen_session)
from nuclemu.experiments.beta import EXPERIMENT
from nuclemu.workbench import Workbench


def course():
    return Experiment("window-test", "Window test", "Fixed input",
        (Parameter("foil", "Foil", "", 0, 0, 1, integer=True),),
        tuple(Device(d, "counter", d, 1, input="detector") for d in ("a", "b")),
        lambda settings, start, end, rng: {"detector": (round(10*(end-start)),)},
        outputs=(SignalOutput("detector", "Detector", 1),))


class WindowExchangeTests(unittest.TestCase):
    def test_true_cli_hot_change_matches_public_acquisition_and_files(self):
        reference = capture_session(acquire())
        for speed, tick in ((1, .25), (2, .125), (8, .05)):
            work = Workbench(seed=42)
            work.switch("beta")
            work.configure({"source_present": 1, "foil_count": 0, "foil_spec_um": 100})
            work.set_output("beta_detector", True)
            work.set_speed(speed)
            work.start(5, device="counter", window_s=1)
            work.start(5, device="counter_b", window_s=5)
            for half in range(2):
                for _ in range(round(2.5/tick)):
                    work.advance(tick/speed)
                    work.product()
                if not half:
                    work.configure({"foil_count": 4})
            work.snapshot(device="counter")
            work.snapshot(device="counter_b")
            self.assertEqual([i["document"] for i in capture_session(work.session)["items"]],
                             [i["document"] for i in reference["items"]])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cli.nuclemu"
            result = subprocess.run([sys.executable, "-m", "nuclemu", "run", "beta",
                "--seed", "42", "--set", "source_present=1", "--set", "foil_spec_um=100",
                "--enable-output", "beta_detector", "--window", "counter=1",
                "--window", "counter_b=5", "--duration", "5", "--change", "2.5,foil_count=4",
                "--package", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = load_package(path)
            inspection = subprocess.run([sys.executable, "-m", "nuclemu", "files", "inspect", str(path)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(inspection.returncode, 0, inspection.stderr)
            self.assertEqual([i["id"] for i in json.loads(inspection.stdout)["items"]],
                             [i["id"] for i in actual["items"]])
            for item, expected in zip(actual["items"], reference["items"]):
                self.assertEqual(item["document"], expected["document"])
                device = item["document"]["snapshot"]["device"]
                for fmt in ("json", "csv"):
                    exported = Path(directory) / f"{device}.{fmt}"
                    result = subprocess.run([sys.executable, "-m", "nuclemu", "files", "export", str(path),
                        "--item", item["id"], "--output", str(exported)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = exported.read_bytes()
                    self.assertEqual(load_item(data)["items"][0], item)
                    decoded = decode_measurement(data, EXPERIMENT, device)
                    self.assertEqual(len(decoded.snapshot.windows), 5 if device == "counter" else 1)
                    if fmt == "csv":
                        rows = list(csv.DictReader(StringIO(data.decode().split("\n", 1)[1])))
                        self.assertEqual(len(rows), len(decoded.snapshot.windows))
            with self.assertRaisesRegex(ValueError, "explicitly"):
                decode_measurement(actual, EXPERIMENT, "counter")
            altered = deepcopy(actual)
            altered["items"][0]["document"]["windows"][2]["parts"][0]["settings"]["foil_count"] = 1
            with self.assertRaisesRegex(ValueError, "conditions"):
                package_bytes(altered)

    def test_source_100_to_103_load_at_zero_continue_and_reopen(self):
        experiment = course()
        source = Session(experiment)
        source.set_output("detector", True)
        source.start(100, device="a")
        source.advance(100)
        source.clear(device="a")
        source.start(3, device="a", window_s=1)
        source.advance(3)
        source.snapshot("a")
        original = capture_session(source)
        source_bytes = package_bytes(original)
        item_id = original["items"][0]["id"]
        for fmt in ("json", "csv"):
            with self.subTest(format=fmt):
                data = export_item(original, item_id, fmt)
                decoded = decode_measurement(data, experiment, "a")
                target = Session(experiment)
                target.configure({"foil": 1})
                target.set_output("detector", True)
                target.start(device="b")
                b = target.instrument("b")
                target.load_measurement("a", decoded.snapshot)
                self.assertEqual(target.time_s, 0)
                self.assertEqual(target.instrument("b"), b)
                self.assertEqual(target.instrument("a").readable_exposure_s, 3)
                target.start(device="a")
                target.advance(1)
                saved = target.snapshot("a")
                self.assertEqual((saved.exposure_s, saved.counts, len(saved.windows)), (4, (40,), 4))
                self.assertEqual(target.instrument("b").readable_exposure_s, 1)
                self.assertEqual([(p.start_s, p.end_s) for w in saved.windows[:3] for p in w.parts],
                                 [(100, 101), (101, 102), (102, 103)])
                self.assertEqual(saved.windows[-1].parts[0].settings["foil"], 1)
                self.assertEqual(saved.windows[0].parts[0].settings["foil"], 0)
                doc = load_package(package_bytes(capture_session(target)))
                reopened = reopen_session(doc, experiment)
                self.assertEqual(reopened.snapshots[0], saved)
                for output in ("json", "csv"):
                    bundle = load_item(export_item(doc, doc["items"][0]["id"], output))
                    self.assertEqual(bundle["items"][0]["document"], doc["items"][0]["document"])
                self.assertEqual(package_bytes(original), source_bytes)
                with self.assertRaises(TypeError):
                    decoded.snapshot.segments[0].settings["foil"] = 1

    def test_old_aggregate_keeps_unknown_prefix_without_inventing_windows(self):
        experiment = course()
        source = Session(experiment)
        source.set_output("detector", True)
        source.start(3, device="a")
        source.advance(3)
        source.snapshot("a")
        old = capture_session(source)
        del old["items"][0]["document"]["windows"]
        decoded = decode_measurement(old, experiment, "a")
        target = Session(experiment)
        target.set_output("detector", True)
        target.load_measurement("a", decoded.snapshot)
        target.snapshot("a")
        prefix_doc = capture_session(target)
        for fmt in ("json", "csv"):
            bundle = load_item(export_item(prefix_doc, prefix_doc["items"][0]["id"], fmt))
            self.assertEqual(bundle["items"][0]["document"], prefix_doc["items"][0]["document"])
        target.start(device="a")
        target.advance(1)
        target.snapshot("a")
        doc = load_package(package_bytes(capture_session(target)))
        product = doc["items"][-1]["document"]
        self.assertEqual(product["window_prefix"], {"exposure_s": 3, "counts": [30]})
        self.assertEqual(len(product["windows"]), 1)
        self.assertEqual(product["windows"][0]["start_exposure_s"], 3)
        for fmt in ("json", "csv"):
            bundle = load_item(export_item(doc, doc["items"][-1]["id"], fmt))
            self.assertEqual(bundle["items"][0]["document"], product)
        self.assertEqual(reopen_session(doc, experiment).snapshots[0].window_prefix_exposure_s, 3)

    def test_pending_window_preset_and_partial_nominal_window_roundtrip(self):
        experiment = course()
        source = Session(experiment)
        source.set_output("detector", True)
        source.start(device="a", window_s=5)
        source.advance(2.5)
        source.configure_acquisition("a", window_s=2)
        source.advance(.5)
        saved = source.snapshot("a")
        self.assertEqual((saved.windows[0].complete, saved.windows[0].window_s), (False, 5))
        doc = load_package(package_bytes(capture_session(source)))
        reopened = reopen_session(doc, experiment)
        self.assertEqual(reopened.instrument("a").window_s, 2)
        self.assertEqual(reopened.rounds[0].window_changes[0].effective_exposure_s, 5)
        for fmt in ("json", "csv"):
            decoded = decode_measurement(export_item(doc, doc["items"][0]["id"], fmt), experiment, "a")
            target = Session(experiment)
            target.set_output("detector", True)
            target.load_measurement("a", decoded.snapshot)
            target.start(device="a")
            target.advance(2)
            completed = target.snapshot("a")
            self.assertEqual(len(completed.windows), 1)
            self.assertEqual((completed.windows[0].complete, completed.windows[0].counts,
                              completed.windows[0].end_exposure_s), (True, (50,), 5))


if __name__ == "__main__":
    unittest.main()
