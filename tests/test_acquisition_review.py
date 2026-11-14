"""PR review operations at nonintegral times and instrument window boundaries."""

from math import floor
from dataclasses import replace
from copy import deepcopy
from hashlib import sha256
from random import Random
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.catalog import discover
from nuclemu.results import Calibration
from nuclemu.workbench import Workbench
from nuclemu.exchange import capture_session, save_package, load_package, reopen_session, export_item, decode_measurement


def lab():
    definition = Experiment("review-pulses", "Review pulses", "Known 10 pulses/s.",
        (Parameter("foil", "Foil", "", 0, 0, 4),),
        (Device("a", "counter", "A", input="out"), Device("b", "counter", "B", input="out")),
        lambda settings, start, end, rng: {"out": (floor(end * 10) - floor(start * 10),)},
        outputs=(SignalOutput("out", "Detector"),))
    session = Session(definition, 187)
    session.set_output("out", True)
    return session


class AcquisitionReviewTests(unittest.TestCase):
    def test_explicit_group_start_stop_is_atomic_and_does_not_control_other_instruments(self):
        source = lab()
        definition = replace(source.experiment, devices=(*source.experiment.devices,
                             Device("c", "counter", "Other instrument", input="out")))
        s = Session(definition)
        s.set_output("out", True)
        s.start(device="c")
        s.configure_acquisition("a", duration_s=1, window_s=1)
        s.configure_acquisition("b", duration_s=5, window_s=5)
        s.start_group(("a", "b"))
        s.advance(1.25)
        before = s.instrument("a"), s.instrument("b"), list(s.records), s._rng.getstate()
        with self.assertRaisesRegex(ValueError, "limit reached"):
            s.start_group(("b", "a"))
        self.assertEqual(before, (s.instrument("a"), s.instrument("b"), s.records, s._rng.getstate()))
        s.stop_group(("a", "b"))
        self.assertTrue(s.instrument("c").running)
        self.assertTrue(s.output_enabled["out"])
        with self.assertRaisesRegex(ValueError, "Pause"):
            s.configure_group(("a", "c"), duration_s=5)
        self.assertEqual(s.instrument("a").duration_s, 1)
        s.configure_group(("a", "b"), duration_s=5, count_limit=None)
        self.assertEqual((s.instrument("a").window_s, s.instrument("b").window_s), (1, 5))
        s.start_group(("a", "b"))
        self.assertTrue(s.instrument("a").running)
        self.assertTrue(s.instrument("b").running)
        self.assertEqual(s.time_s, 1.25)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            s.stop_group(("a", "unknown"))
        self.assertTrue(s.instrument("a").running)

    def test_same_clock_loaded_prefix_is_not_merged_with_new_origin(self):
        s = lab()
        s.start(device="a")
        s.advance(3)
        s.snapshot("a")
        doc = capture_session(s)
        restored = reopen_session(doc, s.experiment)
        decoded = decode_measurement(doc, s.experiment, "a")
        restored.load_measurement("a", decoded.snapshot)
        restored.set_output("out", True)
        restored.start(device="a")
        restored.advance(1)
        saved = restored.snapshot("a")
        self.assertEqual(len(saved.segments), 2)
        self.assertIsNotNone(saved.segments[0].origin)
        self.assertIsNone(saved.segments[1].origin)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "same-clock.nuclemu"
            save_package(path, capture_session(restored, doc))
            final = reopen_session(load_package(path), s.experiment)
            self.assertEqual(len(final.snapshots[-1].windows), 4)
            self.assertEqual(final.snapshots[-1].counts, (40,))

    def test_whole_cross_condition_spectrum_readout_preserves_total_and_parts(self):
        w = Workbench(definitions={"alpha": discover()["alpha"]}, seed=187)
        w.configure({"source_present": 1, "foil_count": 0})
        w.set_output("alpha_detector", True)
        w.start(device="mca")
        w.advance(2)
        w.configure({"foil_count": 1})
        w.advance(1)
        saved = w.snapshot()
        before = w.session.records.copy(), w.session._rng.getstate(), w.lab.selected
        cal = Calibration("alpha", "mca", 1024, 0, 0, 1000, 6)
        result = w.readout_snapshot(saved, 850, 900, calibration=cal)
        self.assertEqual((result["counts"], result["exposure_s"]), (221, 3))
        self.assertEqual([sum(p.readings["mca"]) for p in saved.segments], [153, 68])
        self.assertEqual(result["roi_counts"], sum(saved.counts[850:901]))
        self.assertEqual((w.session.records, w.session._rng.getstate(), w.lab.selected), before)
        with self.assertRaisesRegex(ValueError, "different instrument"):
            w.readout_snapshot(saved, calibration=replace(cal, experiment="another-course"))

    def test_foreign_time_prefix_load_json_csv_continue_and_reopen(self):
        source = lab()
        source.configure({"foil": 4})
        source.advance(100)
        source.start(device="a")
        source.advance(3)
        source.snapshot("a")
        doc = capture_session(source)
        original = deepcopy(doc)
        for format in ("json", "csv"):
            with self.subTest(format=format):
                target = lab()
                target.configure({"foil": 2})
                target.start(device="b")
                decoded = decode_measurement(export_item(doc, doc["items"][0]["id"], format), target.experiment, "a")
                target.load_measurement("a", decoded.snapshot)
                self.assertEqual(target.time_s, 0)
                self.assertEqual(target.rounds[-1].initial_settings["foil"], 2)
                self.assertEqual(target.instrument("a").counts, (30,))
                self.assertEqual(len(target.instrument_windows("a")), 3)
                target.start(device="a")
                target.advance(1)
                self.assertEqual((target.instrument("a").counts, target.instrument("a").exposure_s), ((40,), 4))
                self.assertEqual((target.instrument("b").counts, target.instrument("b").exposure_s), ((10,), 1))
                windows = target.instrument_windows("a")
                self.assertEqual(len(windows), 4)
                self.assertEqual((windows[0].parts[0].start_s, windows[2].parts[-1].end_s), (100, 103))
                self.assertEqual(windows[0].parts[0].settings["foil"], 4)
                self.assertEqual(windows[-1].parts[0].settings["foil"], 2)
                target.snapshot("a")
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "loaded.nuclemu"
                    save_package(path, capture_session(target))
                    reopened = reopen_session(load_package(path), target.experiment)
                    self.assertEqual(reopened.snapshots[0].windows, target.snapshots[0].windows)
                self.assertEqual(doc, original)

    def test_invalid_or_unconfirmed_load_preserves_both_gates_and_rng(self):
        source = lab()
        source.start(device="a")
        source.advance(3)
        saved = source.snapshot("a")
        target = lab()
        target.start(device="a")
        target.start(device="b")
        target.advance(.25)
        def state():
            return target.instrument("a"), target.instrument("b"), target.records.copy(), target._rng.getstate(), target.time_s
        before = state()
        with self.assertRaisesRegex(ValueError, "confirmation"):
            target.load_measurement("a", saved)
        self.assertEqual(state(), before)
        with self.assertRaises(ValueError):
            target.load_measurement("a", replace(saved, counts=(31,)), overwrite=True)
        self.assertEqual(state(), before)

    def test_reopen_uses_versioned_generation_not_initial_stream_and_is_reproducible(self):
        s = lab()
        s.start(device="a")
        s.advance(3)
        s.snapshot("a")
        doc = capture_session(s)
        left, right = reopen_session(doc, s.experiment), reopen_session(doc, s.experiment)
        expected = Random(int.from_bytes(sha256(b"python-random-sha256-v1:187:1").digest(), "big")).getstate()
        self.assertEqual(left._rng.getstate(), expected)
        self.assertEqual(right._rng.getstate(), expected)
        self.assertNotEqual(expected, Random(187).getstate())
        self.assertEqual(left.snapshots, s.snapshots)
        second = reopen_session(capture_session(left, doc), s.experiment)
        self.assertEqual(second.random_stream["generation"], 2)
        legacy = deepcopy(doc)
        legacy.pop("random_stream")
        self.assertEqual(reopen_session(legacy, s.experiment).random_stream["generation"], 1)

    def test_clear_cancel_and_failed_writer_at_five_point_five_export_and_reopen(self):
        for failure in (False, True):
            with self.subTest(writer_failure=failure):
                s = lab()
                s.start(device="a")
                s.start(device="b")
                s.advance(3)
                request = s.begin_clear("a")
                self.assertEqual(s.pending_clear("a"), request)
                s.advance(2.5)
                if failure:
                    def writer(item):
                        raise OSError("cache failed")
                    with self.assertRaises(OSError):
                        s.finish_clear("a", request.token, "save", writer=writer)
                else:
                    s.finish_clear("a", request.token, "cancel")
                self.assertIsNone(s.pending_clear("a"))
                s.advance(.5)
                self.assertEqual((s.instrument("a").counts, s.instrument("a").readable_exposure_s), ((35,), 3.5))
                self.assertEqual((s.instrument("b").counts, s.instrument("b").readable_exposure_s), ((60,), 6))
                s.snapshot("a")
                s.snapshot("b")
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "review.nuclemu"
                    save_package(path, capture_session(s))
                    reopened = reopen_session(load_package(path), s.experiment)
                    self.assertEqual([(v.counts, v.exposure_s) for v in reopened.snapshots], [((35,), 3.5), ((60,), 6)])

    def test_clear_preserves_duration_count_target_and_window(self):
        for choice in ("save", "discard"):
            s = lab()
            s.configure_acquisition("a", duration_s=10, count_limit=500, window_s=5)
            s.start(device="a")
            s.advance(3)
            request = s.begin_clear("a")
            s.finish_clear("a", request.token, choice)
            state = s.instrument("a")
            self.assertEqual((state.duration_s, state.count_limit, state.window_s, state.exposure_s), (10, 500, 5, 0))
            s.start(device="a")
            s.advance(11)
            self.assertEqual(s.instrument("a").exposure_s, 10)
            self.assertEqual(s.instrument("a").stop_reason, "time_limit")

    def test_windows_cross_conditions_without_splitting_and_hot_length_applies_next_window(self):
        s = lab()
        s.start(device="a", window_s=1)
        s.start(device="b", window_s=5)
        s.advance(2.5)
        s.configure({"foil": 4})
        s.advance(2.5)
        a, b = s.instrument_windows("a"), s.instrument_windows("b")
        self.assertEqual([w.counts for w in a], [(10,)] * 5)
        self.assertEqual([w.counts for w in b], [(50,)])
        self.assertEqual({p.settings["foil"] for p in a[2].parts}, {0, 4})
        self.assertEqual({p.settings["foil"] for p in b[0].parts}, {0, 4})
        saved = s.snapshot("a")
        s.advance(.25)
        s.configure_acquisition("a", duration_s=None, count_limit=None, window_s=2)
        s.advance(.75)
        self.assertEqual(s.instrument_windows("a")[-1].counts, (10,))
        s.advance(2)
        self.assertEqual(s.instrument_windows("a")[-1].counts, (20,))
        self.assertEqual(len(saved.windows), 5)


if __name__ == "__main__":
    unittest.main()
