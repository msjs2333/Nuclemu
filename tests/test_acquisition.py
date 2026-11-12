"""Shared physical output, independent exposure gates and one laboratory clock."""

from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe, discover
from nuclemu.core import Device, Session, SignalOutput
from nuclemu.results import MeasurementView, collect, write_product
from nuclemu.workbench import Workbench


COURSES = Path(__file__).resolve().parents[1] / "examples" / "courses"


def definition():
    return discover([COURSES])["split-signal"]


def rows(session, device):
    return [row for row in session.records if device in row.readings]


def total(session, device):
    return sum(sum(row.readings[device]) for row in rows(session, device))


class AcquisitionTests(unittest.TestCase):
    def test_idle_detector_only_and_zero_input_exposure(self):
        s = Session(definition())
        s.advance(100)
        self.assertEqual(s.time_s, 0)
        s.set_output("detector", True)
        s.advance(2.25)
        self.assertTrue(s.clock_running)
        self.assertFalse(s.running)
        self.assertEqual(s.records, [])
        s.set_output("detector", False)
        s.advance(100)
        self.assertEqual(s.time_s, 2.25)
        s.start(1.5, device="a")
        s.advance(100)
        self.assertEqual(s.time_s, 3.75)
        self.assertFalse(s.clock_running)
        self.assertEqual(s.instrument("a").exposure_s, 1.5)
        self.assertEqual(total(s, "a"), 0)
        self.assertEqual(rows(s, "b"), [])

    def test_output_off_during_gate_preserves_ten_seconds(self):
        s = Session(definition(), seed=187)
        s.set_output("detector", True)
        for device in ("a", "b"):
            s.start(10, device=device)
        s.advance(3)
        s.set_output("detector", False)
        s.advance(4)
        s.set_output("detector", True)
        s.advance(3)
        for device in ("a", "b"):
            selected = rows(s, device)
            self.assertEqual(sum(r.exposure_s for r in selected), 10)
            off = [r for r in selected if r.start_s >= 3 and r.end_s <= 7]
            self.assertEqual(sum(r.exposure_s for r in off), 4)
            self.assertTrue(all(r.readings[device] == (0,) for r in off))
        self.assertEqual([r.readings["a"] for r in rows(s, "a")],
                         [r.readings["b"] for r in rows(s, "b")])
        self.assertEqual(s.time_s, 10)
        self.assertTrue(s.clock_running)  # Detector still on after both timed gates.
        s.set_output("detector", False)
        s.advance(100)
        self.assertEqual(s.time_s, 10)

    def test_a_closes_while_b_keeps_both_shared_intervals(self):
        s = Session(definition(), seed=42)
        s.set_output("detector", True)
        s.start(5, device="a")
        s.start(10, device="b")
        s.advance(5)
        first = total(s, "a")
        self.assertEqual(first, total(s, "b"))
        self.assertFalse(s.instrument("a").running)
        s.snapshot("a")
        s.clear(device="a")
        s.start(5, device="a")
        s.advance(5)
        self.assertEqual(total(s, "a"), total(s, "b"))
        self.assertEqual([r.acquisition for r in rows(s, "a")], [1]*5 + [2]*5)
        self.assertEqual(s.instrument("b").exposure_s, 10)

    def test_manual_partial_stop_does_not_stop_other_instrument(self):
        s = Session(definition(), seed=42)
        s.set_output("detector", True)
        s.start(device="a")
        s.start(device="b")
        s.advance(2.4)
        s.stop(device="a")
        first = total(s, "a")
        self.assertEqual(first, total(s, "b"))
        s.advance(.6)
        s.stop(device="b")
        self.assertEqual(total(s, "a"), first)
        self.assertEqual(s.instrument("a").exposure_s, 2.4)
        self.assertEqual(s.instrument("b").exposure_s, 3)
        self.assertTrue(s.clock_running)

    def test_seed_and_physical_timeline_ignore_refresh_speed_and_batch_size(self):
        def run(speed, chunk):
            bench = Workbench(definitions={"split": definition()}, seed=42)
            bench.set_speed(speed)
            bench.set_output("detector", True)
            bench.start(device="a")
            bench.start(7.5, device="b")
            for seconds in (2.4, 1.6, 3.5):
                count = max(1, round(seconds / chunk))
                for _ in range(count):
                    bench.advance(round(seconds / count, 12) / speed)
                    bench.product()
                if seconds == 2.4:
                    bench.stop(device="a")
                elif seconds == 1.6:
                    bench.set_output("detector", False)
            return bench
        left, right = run(1, 100), run(8, .1)
        self.assertEqual(left.session.records, right.session.records)
        self.assertEqual(left.session.time_s, 7.5)
        self.assertEqual(left.product(), right.product())

    def test_invalid_operations_and_failed_model_do_not_commit(self):
        bad = [True]
        original = definition()
        def model(*args):
            value = original.model(*args)
            if bad:
                bad.pop()
                return {"detector": (-1,)}
            return value
        s = Session(replace(original, model=model), seed=42)
        s.set_output("detector", True)
        s.start(device="a")
        for action in (lambda: s.start(device="missing"), lambda: s.stop(device="missing"),
                       lambda: s.set_output("detector", 1), lambda: s.start(0, device="b")):
            with self.assertRaises(ValueError):
                action()
        with self.assertRaisesRegex(ValueError, "nonnegative integer"):
            s.advance(1)
        self.assertEqual(s.time_s, 0)
        self.assertEqual(s.records, [])
        s.advance(1)
        ref = Session(original, seed=42)
        ref.set_output("detector", True)
        ref.start(device="a")
        ref.advance(1)
        self.assertEqual(s.records, ref.records)

    def test_sparse_products_keep_each_instruments_actual_exposure(self):
        bench = Workbench(definitions={"split": definition()}, seed=42)
        bench.set_output("detector", True)
        bench.start(2, device="a")
        bench.start(3, device="b")
        view = MeasurementView(bench.session)
        for _ in range(3):
            bench.advance(1)
            view.product()
        self.assertEqual(view.product(), collect(definition(), bench.session.records, 42))
        for device, exposure in (("a", 2), ("b", 3)):
            bench.bind_device(device)
            self.assertEqual(bench.readout()["exposure_s"], exposure)
            stream = StringIO()
            write_product(stream, "json", view.product(), device=device)
            selected = json.loads(stream.getvalue())
            self.assertEqual(len(selected["segments"]), 1)
            self.assertEqual(selected["segments"][0]["end_s"], exposure)

    def test_bindings_rejected_at_definition_boundary(self):
        base = definition()
        for change in (
            {"outputs": (SignalOutput("detector", "D", unit="1/s"),)},
            {"outputs": (SignalOutput("detector", "D", channels=2),)},
            {"devices": (Device("a", "counter", "A", input="missing"),)},
            {"outputs": ()},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(base, **change)
        self.assertEqual(describe(base)["outputs"][0]["time_unit"], "s")
        entry = describe(base)
        self.assertEqual([part["output"] for part in entry["components"] if part["output"]], ["detector"])
        self.assertEqual([(link["source"], link["target"]) for link in entry["connections"]],
                         [("output-detector", "device-a"), ("output-detector", "device-b")])

    def test_default_exports_and_background_follow_displayed_device(self):
        bench = Workbench(definitions={"split": definition()}, seed=42)
        bench.start(2, device="a")
        bench.start(3, device="b")
        bench.advance(100)
        with TemporaryDirectory() as folder:
            for device, exposure in (("a", 2), ("b", 3)):
                bench.bind_device(device)
                for suffix in ("json", "csv"):
                    path = Path(folder) / f"{device}.{suffix}"
                    bench.export(path)
                    text = path.read_text(encoding="utf-8")
                    if suffix == "json":
                        segment, = json.loads(text)["segments"]
                        self.assertEqual(segment["end_s"] - segment["start_s"], exposure)
                        self.assertEqual(list(segment["readings"]), [device])
                    else:
                        self.assertIn(f",{device},", text)
                        self.assertIn(f",{float(exposure)},", text)
            bench.bind_device("a")
            bench.select(0)
            bench.set_background(0)
            bench.bind_device("b")
            self.assertIsNone(bench.lab.selected)
            self.assertIsNone(bench.lab.background)
            self.assertEqual(bench.readout()["exposure_s"], 3)


if __name__ == "__main__":
    unittest.main()
