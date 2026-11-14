"""Measurement rounds, complete-window count limits and local clear holds."""

from dataclasses import replace
from math import floor
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from nuclemu.catalog import discover
from nuclemu.core import Component, Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.results import MeasurementView, round_document
from nuclemu.workbench import Workbench


def periodic(settings, start, end, rng):
    return {"out": (floor(end * 10) - floor(start * 10),)}


def definition(model=periodic):
    return Experiment("rounds", "Rounds", "", (),
                      (Device("a", "counter", "A", input="out"),
                       Device("b", "counter", "B", input="out")), model,
                      outputs=(SignalOutput("out", "Detector"),))


def running(model=periodic):
    s = Session(definition(model))
    s.set_output("out", True)
    return s


class RoundTests(unittest.TestCase):
    def test_manual_pause_and_continue_keep_round_and_exclude_paused_input(self):
        s = running()
        s.start(device="a")
        s.advance(2.4)
        s.stop(device="a")
        first = s.instrument("a")
        self.assertEqual((first.counts, first.exposure_s, first.acquisition), ((24,), 2.4, 1))
        s.advance(2)
        s.start(device="a")
        self.assertEqual(s.instrument("a").cycle, 2)
        s.advance(.6)
        s.stop(device="a")
        second = s.instrument("a")
        self.assertEqual((second.counts, second.exposure_s, second.acquisition), ((30,), 3, 1))
        self.assertEqual([r.acquisition for r in s.records], [1, 1, 1, 1])

    def test_count_limit_closes_only_after_full_statistics_window(self):
        def prefix(t):
            values = (42, 47, 18, 30, 30)
            whole = floor(t)
            return sum(values[:whole]) + (values[whole] * (t-whole) if whole < len(values) else 0)
        def model(settings, start, end, rng):
            return {"out": (round(prefix(end)-prefix(start)),)}
        results = []
        for chunk in (1, .1, 5):
            s = running(model)
            s.start(device="a", count_limit=100)
            for _ in range(round(5/chunk)):
                s.advance(chunk)
            state = s.instrument("a")
            self.assertEqual((state.counts, state.exposure_s, state.stop_reason), ((107,), 3, "count_limit"))
            self.assertFalse(state.running)
            with self.assertRaisesRegex(ValueError, "clear"):
                s.start(device="a")
            results.append(s.records)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_partial_pause_preserves_remaining_time_and_window(self):
        s = running()
        s.start(3, device="a", count_limit=29)
        s.advance(2.4)
        s.stop(device="a")
        self.assertAlmostEqual(s.instrument("a").remaining_s, .6)
        s.advance(2)
        s.start(device="a")
        s.advance(.6)
        self.assertEqual(s.instrument("a").counts, (30,))
        self.assertEqual(s.instrument("a").exposure_s, 3)
        self.assertEqual(s.instrument("a").stop_reason, "time_limit")

    def test_configured_window_is_not_replaced_by_display_or_physical_windows(self):
        s = running()
        s.start(device="a", count_limit=11, window_s=2)
        s.advance(1.5)
        s.stop(device="a")
        self.assertEqual(s.instrument("a").counts, (15,))
        # The target has already been crossed, but only a full 2 s window may
        # enforce it. A manual stop must remain resumable until that boundary.
        s.start(device="a")
        s.advance(.5)
        self.assertEqual(s.instrument("a").counts, (20,))
        self.assertEqual(s.instrument("a").stop_reason, "count_limit")

    def test_snapshots_are_detached_and_do_not_sample_or_stop(self):
        s = running()
        s.start(device="a")
        s.advance(3)
        first = s.snapshot("a")
        s.advance(2)
        second = s.snapshot("a")
        self.assertEqual((first.counts, first.exposure_s), ((30,), 3))
        self.assertEqual((second.counts, second.exposure_s), ((50,), 5))
        self.assertEqual(first.acquisition, second.acquisition)
        self.assertEqual(len(s.snapshots), 2)
        s.advance(.4)
        before = (s._rng.getstate(), list(s.records))
        partial = s.snapshot("a", cache=False)
        self.assertEqual((partial.counts, partial.exposure_s), ((50,), 5))
        self.assertEqual(before, (s._rng.getstate(), s.records))
        self.assertTrue(s.instrument("a").running)
        with self.assertRaises(AttributeError):
            first.counts = (0,)

    def test_paused_targets_can_extend_same_round_without_opening_or_resetting(self):
        s = running()
        s.start(1, device="a")
        s.start(device="b")
        s.advance(1)
        saved = s.snapshot("a")
        other = s.instrument("b")
        s.configure_acquisition("a", duration_s=3, window_s=1)
        self.assertFalse(s.instrument("a").running)
        self.assertEqual(s.instrument("a").counts, (10,))
        self.assertEqual(s.instrument("b"), other)
        s.start(device="a")
        s.advance(2)
        state = s.instrument("a")
        self.assertEqual((state.acquisition, state.counts, state.exposure_s), (1, (30,), 3))
        self.assertFalse(state.running)
        self.assertEqual((saved.counts, saved.exposure_s), ((10,), 1))
        self.assertEqual(s.rounds[0].initial_duration_s, 1)
        self.assertEqual(s.rounds[0].target_changes[0].duration_s, 3)
        s.configure_acquisition("a", duration_s=None)
        s.start(device="a")
        s.advance(1)
        self.assertTrue(s.instrument("a").running)
        self.assertEqual(s.instrument("a").counts, (40,))
        with self.assertRaisesRegex(ValueError, "Pause"):
            s.configure_acquisition("a", count_limit=50)

    def test_count_limited_round_can_raise_target_or_return_to_ordinary(self):
        for new_target in (None, 50):
            s = running()
            s.configure_acquisition("a", count_limit=15, window_s=2)
            s.start(device="a")
            s.advance(2)
            self.assertEqual(s.instrument("a").counts, (20,))
            self.assertEqual(s.instrument("a").stop_reason, "count_limit")
            saved = s.snapshot("a")
            s.configure_acquisition("a", count_limit=new_target)
            self.assertFalse(s.instrument("a").running)
            s.start(device="a")
            s.advance(4)
            self.assertEqual(s.instrument("a").acquisition, 1)
            self.assertEqual(s.instrument("a").counts, (60,))
            self.assertEqual(s.instrument("a").running, new_target is None)
            self.assertEqual(saved.counts, (20,))

    def test_clear_save_discard_cancel_and_failure_hold_only_target(self):
        for choice in ("save", "discard", "cancel", "failure"):
            with self.subTest(choice=choice):
                s = running()
                s.start(10, device="a")
                s.start(device="b")
                s.advance(3)
                request = s.begin_clear("a")
                self.assertEqual(s.begin_clear("a"), request)
                self.assertEqual(request.snapshot.exposure_s, 3)
                s.advance(2)
                self.assertEqual(s.instrument("b").exposure_s, 5)
                self.assertEqual(s.instrument("a").exposure_s, 3)
                self.assertEqual(s.instrument("a").remaining_s, 7)
                def fail(snapshot):
                    self.assertEqual(s.instrument("b").exposure_s, 5)
                    raise OSError("cache failed")
                if choice == "failure":
                    with self.assertRaisesRegex(OSError, "cache failed"):
                        s.finish_clear("a", request.token, "save", writer=fail)
                else:
                    s.finish_clear("a", request.token, choice)
                if choice in ("cancel", "failure"):
                    self.assertTrue(s.instrument("a").running)
                    self.assertEqual(s.instrument("a").acquisition, 1)
                    s.advance(7)
                    self.assertEqual(s.instrument("a").exposure_s, 10)
                    self.assertEqual(s.instrument("a").counts, (100,))
                else:
                    self.assertIsNone(s.instrument("a").acquisition)
                    self.assertEqual(s.instrument("a").counts, (0,))
                    self.assertEqual(len(s.snapshots), int(choice == "save"))
                    if choice == "save":
                        self.assertEqual(s.snapshots[0].exposure_s, 3)
                    s.start(device="a")
                    self.assertEqual(s.instrument("a").acquisition, 2)
                with self.assertRaisesRegex(ValueError, "expired"):
                    s.finish_clear("a", request.token, "discard")

    def test_multiple_live_tails_report_first_changed_index(self):
        s = running()
        s.start(device="a")
        s.start(device="b")
        view = MeasurementView(s)
        s.advance(1)
        view.product()
        s.advance(1)
        product = view.product()
        self.assertEqual(view.changed_start, 0)
        self.assertEqual([r["end_s"] for r in product["segments"]], [2, 2])
        old_cursor = len(s.records)
        s.stop(device="a")
        s.advance(1)
        view.product()
        self.assertEqual(view.changed_start, 1)
        self.assertEqual(view.changed_start_since(2), 0)
        self.assertEqual(view.changed_start_since(old_cursor), 1)

    def test_round_metadata_does_not_create_snapshots_or_persist_unsaved_readings(self):
        lab = replace(definition(), parameters=(Parameter("x", "X", "", 0, 0, 10),))
        s = Session(lab)
        s.set_output("out", True)
        s.start(device="a")
        s.advance(2)
        s.configure({"x": 2})
        s.configure({"x": 2})
        s.advance(1)
        saved = s.snapshot("a")
        s.advance(2)
        info, = s.rounds
        self.assertEqual((info.exposure_s, saved.exposure_s), (5, 3))
        self.assertEqual(info.initial_settings, {"x": 0})
        self.assertEqual(len(info.changes), 1)
        self.assertEqual(info.changes[0].exposure_s, 2)
        self.assertFalse(hasattr(info, "counts"))
        s.set_output("out", False)
        document = round_document(s.rounds[0])
        self.assertEqual(document["initial_outputs"], {"out": True})
        self.assertEqual(document["output_changes"][0]["values"], {"out": False})
        json.dumps(document)
        s.clear(device="a")
        self.assertEqual(s.rounds[0].exposure_s, 5)
        self.assertEqual(len(s.snapshots), 1)

    def test_workbench_current_readout_and_export_accumulate_gate_cycles(self):
        bench = Workbench(definitions={"rounds": definition()})
        bench.set_output("out", True)
        bench.start(device="a")
        bench.advance(2.4)
        bench.stop(device="a")
        bench.advance(2)
        bench.start(device="a")
        bench.advance(.6)
        bench.stop(device="a")
        self.assertEqual(bench.readout(), {"counts": 30, "exposure_s": 3, "rate": 10})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "current.json"
            bench.export(path)
            product = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(product["snapshot"]["exposure_s"], 3)
            self.assertEqual(sum(s["readings"]["a"][0] for s in product["segments"]), 30)
        bench.clear(device="a")
        self.assertIsNone(bench.readout())

    def test_current_cumulative_round_cannot_treat_its_own_partial_segment_as_independent_background(self):
        lab = replace(definition(), parameters=(Parameter("x", "X", "", 0, 0, 10),))
        bench = Workbench(definitions={"rounds": lab})
        bench.set_output("out", True)
        bench.start(device="a")
        bench.advance(1)
        bench.configure({"x": 2})
        bench.advance(1)
        bench.set_background(0)
        with self.assertRaisesRegex(ValueError, "includes the background"):
            bench.readout()
        self.assertEqual(bench.readout_for(1)["net_rate"], 0)
        self.assertIsNone(bench.lab.selected)
        self.assertTrue(bench.readout_for(0)["background_reference"])
        bench.select(1)
        self.assertEqual(bench.readout()["net_rate"], 0)


class BatchTests(unittest.TestCase):
    def test_batch_validation_is_atomic_and_single_key_uses_same_adapter(self):
        def adapter(values):
            if "old" in values:
                if len(values) != 1:
                    raise ValueError("ambiguous")
                return {"x": values["old"]}
            return values
        base = definition()
        lab = replace(base, parameters=(Parameter("x", "X", "", 0, 0, 10),
                                        Parameter("y", "Y", "", 0, 0, 10)),
                      normalize_settings=adapter)
        s = Session(lab)
        s.set_output("out", True)
        s.start(device="a")
        s.advance(.4)
        before = (dict(s.settings), list(s.records), s.instrument("a"), s._rng.getstate())
        for batch in ({"x": 2, "y": 99}, {"old": 2, "y": 1}):
            with self.assertRaises(ValueError):
                s.configure(batch)
            self.assertEqual(before, (dict(s.settings), s.records, s.instrument("a"), s._rng.getstate()))
        s.configure({"x": 2, "y": 3})
        self.assertEqual(len(s.records), 1)
        self.assertEqual(s.records[0].settings, {"x": 0, "y": 0})
        s.set("old", 4)
        self.assertEqual(s.settings["x"], 4)

    def test_component_output_is_checked(self):
        base = definition()
        parts = (Component("probe", "detector", "Probe", output="bad"),
                 Component("a", "instrument", "A", device="a"),
                 Component("b", "instrument", "B", device="b"))
        with self.assertRaisesRegex(ValueError, "unknown output"):
            replace(base, components=parts)


if __name__ == "__main__":
    unittest.main()
