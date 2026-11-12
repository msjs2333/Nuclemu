"""Shared experiment, instrument, readout and export controller contracts."""

import csv
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.workbench import Workbench
from nuclemu.results import collect, net_count_rate


class WorkbenchTests(unittest.TestCase):
    def test_saved_counter_subtraction_uses_source_and_interval_not_round_number(self):
        definition = Experiment("saved", "Saved", "", (), (Device("counter", "counter", "Counter"),),
                                lambda *args: {"counter": (0,)})
        c = Workbench(definitions={"saved": definition})
        def segment(start, end, counts):
            return dict(start_s=start, end_s=end, acquisition=1, settings={}, readings={"counter": [counts]})
        class View:
            def __init__(self, segments, origins):
                self.segments, self.origins = segments, origins
            def product(self):
                return {"segments": self.segments}
            def measurement_origin(self, index=None):
                return "live-package" if index is None else self.origins[index]
        c.lab.view = View([segment(0, 3, 30), segment(0, 5, 50)], ["package-A", "package-A"])
        c.set_background(0)
        with self.assertRaisesRegex(ValueError, "nonoverlapping"):
            c.readout_for(1)
        self.assertTrue(c.readout_for(0)["background_reference"])
        c.lab.view = View([segment(0, 3, 30), segment(0, 3, 60)], ["package-A", "package-B"])
        self.assertEqual(c.readout_for(1)["net_rate"], 10)
        c.lab.view = View([segment(0, 3, 30), segment(3, 5, 20)], ["package-A", "package-A"])
        self.assertEqual(c.readout_for(1)["net_rate"], 0)
        self.assertIsNone(c.lab.selected)

    def test_roi_counts_and_mixed_gain_cumulative_calibration(self):
        definition = Experiment("gain", "Gain", "",
            (Parameter("gain", "Gain", "", 1, 1, 2),),
            (Device("mca", "spectrum", "MCA", 4, calibration_parameters=("gain",), input="out"),),
            lambda settings, start, end, rng: {"out": (1, 2, 3, 4)},
            outputs=(SignalOutput("out", "Detector", channels=4),))
        c = Workbench(definitions={"gain": definition})
        c.set_output("out", True)
        c.start(device="mca")
        c.advance(1)
        history = c.snapshot(cache=False)
        c.configure({"gain": 2})
        c.advance(1)
        c.select(1)
        calibration = c.calibrate(0, 0, 3, 6)
        single = c.readout(1, 2)
        self.assertEqual(single["roi_counts"], 5)
        self.assertAlmostEqual(single["energy_MeV"], 3.2)
        c.select(None)
        cumulative = c.readout(1, 2)
        self.assertEqual((cumulative["counts"], cumulative["roi_counts"]), (20, 10))
        self.assertAlmostEqual(cumulative["centroid"], 1.6)
        self.assertIsNone(cumulative["energy_MeV"])
        self.assertIsNone(c.active_calibration())
        self.assertAlmostEqual(c.readout_for(1, 1, 2)["energy_MeV"], 3.2)
        with self.assertRaisesRegex(ValueError, "matching instrument settings"):
            c.calibrate(0, 0, 3, 6)
        self.assertEqual(c.lab.calibrations["mca"], calibration)
        with self.assertRaisesRegex(ValueError, "does not match"):
            c.apply_calibration(calibration)
        single_channel = c.readout(0, 0)
        self.assertEqual(single_channel["roi_counts"], 2)
        with self.assertRaises(ValueError):
            c.readout(0, 4)
        before = (dict(c.session.settings), c.session.records.copy(), c.session.instrument("mca"),
                  c.lab.selected, c.session._rng.getstate())
        historical_calibration = c.calibrate_snapshot(history, 0, 0, 3, 3)
        self.assertEqual(dict(historical_calibration.conditions), {"gain": 1})
        self.assertAlmostEqual(c.readout_snapshot(history, 1, 2, calibration=historical_calibration)["energy_MeV"], 1.6)
        with self.assertRaisesRegex(ValueError, "does not match"):
            c.apply_snapshot_calibration(history, calibration)
        with self.assertRaisesRegex(ValueError, "matching instrument settings"):
            c.calibrate_snapshot(c.snapshot(cache=False), 0, 0, 3, 6)
        c.apply_snapshot_calibration(history, historical_calibration)
        self.assertEqual(c.lab.calibrations["mca"], historical_calibration)
        self.assertEqual((dict(c.session.settings), c.session.records, c.session.instrument("mca"),
                          c.lab.selected, c.session._rng.getstate()), before)

    def test_beta_reference_reading_background_export_and_repeated_display(self):
        c = Workbench(seed=42)
        c.switch("beta")
        c.set_output("beta_detector", True)
        c.configure({"source_present": "0"})
        c.start(1.25, device="counter")
        c.advance(1.25)
        c.snapshot(device="counter")
        c.clear(device="counter")
        c.configure({"source_present": "1", "foil_count": "4"})
        c.start(2.5, device="counter")
        for _ in range(25):
            c.advance(.1)
            c.readout()
        c.set_background(0)
        self.assertEqual([s["readings"]["counter"] for s in c.product()["segments"]], [[2], [128]])
        reading = c.readout()
        self.assertEqual(reading["exposure_s"], 2.5)
        self.assertEqual((reading["net_rate"], reading["uncertainty"]), net_count_rate(128, 2.5, 2, 1.25))
        records = list(c.session.records)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "beta.json"
            c.export(path, all_segments=True)
            self.assertFalse(c.unsaved())
            expected = dict(c.product(), devices={"counter": c.product()["devices"]["counter"]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)
            c.select(0)
            self.assertTrue(c.readout()["background_reference"])
            c.export(path.with_suffix(".csv"))
            with path.with_suffix(".csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["counts"], "2")
        for _ in range(10):
            c.product()
            c.readout()
        self.assertEqual(records, c.session.records)

    def test_alpha_reference_roi_and_bound_calibration_round_trip(self):
        c = Workbench(seed=187)
        c.switch("alpha")
        c.set_output("alpha_detector", True)
        c.configure({"source_present": 1})
        c.start(device="mca")
        c.advance(2.25)
        c.stop()
        c.snapshot(device="mca")
        c.clear(device="mca")
        c.configure({"foil_spec_um": "1", "foil_count": "5"})
        c.start(1.25, device="mca")
        c.advance(1.25)
        spectra = [s["readings"]["mca"] for s in c.product()["segments"]]
        self.assertEqual(list(map(sum, spectra)), [172, 86])
        self.assertEqual(c.readout(0, 1)["centroid"], None)
        self.assertEqual(c.readout(0, 1)["roi_counts"], 0)
        with self.assertRaises(ValueError):
            c.readout(-1, 5)
        c.select(0)
        peak = c.readout(850, 870)["centroid"]
        self.assertTrue(850 < peak < 870)
        calibration = c.calibrate(0, 0, 1000, 6)
        self.assertAlmostEqual(c.readout(850, 870)["energy_MeV"], peak * .006)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "energy.json"
            calibration.save(path)
            c.load_calibration(path)
            c.export(Path(directory) / "alpha.csv", all_segments=True)
            with (Path(directory) / "alpha.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2048)
            self.assertEqual(sum(int(r["counts"]) for r in rows), 258)
            self.assertEqual(rows[1000]["energy_MeV"], "6.0")
            c.switch("beta")
            with self.assertRaises(ValueError):
                c.load_calibration(path)

    def test_pause_speed_stop_and_switch_preserve_unsaved_partial_exposure(self):
        c = Workbench(seed=187)
        c.set_output("alpha_detector", True)
        c.start(device="mca")
        c.set_speed(2)
        c.advance(.125)
        c.paused = True
        c.advance(20)
        self.assertEqual(c.session.time_s, .25)
        c.switch("beta")
        c.switch("alpha")
        self.assertFalse(c.session.running)
        self.assertEqual(c.readout()["exposure_s"], .25)
        self.assertTrue(c.unsaved())
        c.paused = False
        c.start(.5, device="mca")
        c.advance(.125)
        self.assertEqual(c.readout()["exposure_s"], .5)
        self.assertEqual(c.session.instrument("mca").acquisition, 1)
        for value in (0, -1, "nan", "inf"):
            with self.assertRaises(ValueError):
                c.set_speed(value)

    def test_invalid_parameter_form_is_atomic_and_does_not_close_window(self):
        c = Workbench()
        c.switch("beta")
        c.configure({"source_present": 1})
        c.set_output("beta_detector", True)
        c.start(device="counter")
        c.advance(.25)
        with self.assertRaises(ValueError):
            c.configure({"source_present": 0, "foil_count": 1.5})
        self.assertEqual(c.session.settings["source_present"], 1)
        self.assertEqual(c.session.records, [])
        c.stop()
        self.assertEqual(c.session.records[0].exposure_s, .25)

    def test_same_kind_devices_keep_instance_readings_and_calibration(self):
        definition = Experiment("two", "Two spectra", "", (),
            (Device("left", "spectrum", "MCA", 4), Device("right", "spectrum", "MCA", 4)),
            lambda settings, start, end, rng: {"left": [0, 2, 0, 0], "right": [0, 0, 5, 0]})
        c = Workbench(definitions={"two": definition})
        c.start(1)
        c.advance(1)
        self.assertEqual(c.readout()["centroid"], 1)
        calibration = c.calibrate(0, 0, 3, 6)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "left.json"
            calibration.save(path)
            c.export(Path(directory) / "left-reading.json")
            self.assertTrue(c.unsaved())  # right has not been exported
            c.bind_device("right")
            self.assertEqual(c.readout()["centroid"], 2)
            self.assertIsNone(c.readout()["energy_MeV"])
            with self.assertRaisesRegex(ValueError, "different instrument"):
                c.load_calibration(path)
            c.export(Path(directory) / "right-reading.json")
            self.assertFalse(c.unsaved())
        with self.assertRaises(ValueError):
            c.bind_device("missing")

    def test_refresh_partition_does_not_change_real_measurements(self):
        for experiment, seed, first, second, setting in (
                ("alpha", 187, 2.25, 1.25, {"foil_um": 5}),
                ("beta", 42, 1.25, 2.5, {"source_present": 1, "foil_count": 4})):
            c = Workbench(seed=seed)
            c.switch(experiment)
            reference = Session(c.session.experiment, seed)
            device = "mca" if experiment == "alpha" else "counter"
            output = c.session.experiment.devices[0].input
            c.set_output(output, True)
            reference.set_output(output, True)
            if experiment == "beta":
                c.configure({"source_present": 0})
                reference.set("source_present", 0)
            c.start(first, device=device)
            reference.start(first, device=device)
            reference.advance(first)
            for _ in range(int(first / .05)):
                c.advance(.05)
                c.product()
            c.configure(setting)
            reference.configure(setting)
            c.clear(device=device)
            reference.clear(device=device)
            c.start(second, device=device)
            reference.start(second, device=device)
            reference.advance(second)
            for _ in range(int(second / .05)):
                c.advance(.05)
                c.readout()
            self.assertEqual(c.product(), collect(reference.experiment, reference.records, seed))


class SaveTrackingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "reading.json"
        self.c = Workbench(seed=42)
        self.c.switch("beta")
        self.c.set_output("beta_detector", True)
        for _ in range(2):
            self.c.clear(device="counter")
            self.c.start(1, device="counter")
            self.c.advance(1)

    def test_overwriting_single_segment_invalidates_only_replaced_coverage(self):
        c = self.c
        c.select(0)
        c.export(self.path)
        c.export(self.path)  # Repeated saves do not create phantom copies.
        c.select(1)
        c.export(self.path)
        self.assertTrue(c.unsaved())
        self.assertEqual(c.lab.saved, {(1, "counter"): 2})
        self.assertEqual(len(json.loads(self.path.read_text())["segments"]), 1)
        c.export(self.path, all_segments=True)
        self.assertFalse(c.unsaved())
        c.select(0)
        c.export(self.path)
        self.assertTrue(c.unsaved())

    def test_independent_duplicate_file_preserves_copy_when_other_is_overwritten(self):
        c = self.c
        backup = self.path.with_name("copy.json")
        c.select(0)
        c.export(self.path)
        c.export(backup)
        c.select(1)
        c.export(self.path)
        self.assertFalse(c.unsaved())
        c.export(backup)
        self.assertTrue(c.unsaved())

    def test_lexical_and_case_aliases_replace_the_same_target(self):
        c = self.c
        child = self.path.parent / "child"
        child.mkdir()
        c.select(0)
        c.export(self.path)
        c.select(1)
        c.export(child / ".." / self.path.name)
        self.assertTrue(c.unsaved())
        if os.name == "nt":
            c.export(self.path, all_segments=True)
            c.export(self.path.with_name(self.path.name.upper()))
            self.assertTrue(c.unsaved())

    def test_replacing_a_hardlink_keeps_the_other_file_and_its_coverage(self):
        c = self.c
        c.select(0)
        c.export(self.path)
        alias = self.path.with_name("hardlink.json")
        try:
            os.link(self.path, alias)
        except OSError as error:
            self.skipTest(str(error))
        c.select(1)
        c.export(alias)
        self.assertFalse(c.unsaved())
        self.assertEqual(json.loads(self.path.read_text())["segments"][0]["start_s"], 0)
        self.assertEqual(json.loads(alias.read_text())["segments"][0]["start_s"], 1)
        c.export(self.path)
        self.assertTrue(c.unsaved())
        c.export(self.path, all_segments=True)
        self.assertFalse(c.unsaved())

    def test_symlink_alias_is_one_copy(self):
        c = self.c
        c.select(0)
        c.export(self.path)
        alias = self.path.with_name("symlink.json")
        try:
            alias.symlink_to(self.path)
        except OSError as error:
            self.skipTest(str(error))
        c.select(1)
        c.export(alias)
        self.assertTrue(c.unsaved())

    def test_partial_write_preserves_old_product_and_allows_retry(self):
        def fail_during_write(*args, **kwargs):
            stream = NamedTemporaryFile(*args, **kwargs)
            write = stream.write

            def partial(text):
                write(text[:8])
                raise OSError("disk full")

            stream.write = partial
            return stream

        c = self.c
        for suffix in (".json", ".csv"):
            with self.subTest(suffix=suffix):
                path = self.path.with_suffix(suffix)
                c.export(path, all_segments=True)
                original = path.read_bytes()
                files = set(path.parent.iterdir())
                c.select(1)
                with patch("nuclemu.results.NamedTemporaryFile", side_effect=fail_during_write):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        c.export(path)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(set(path.parent.iterdir()), files)
                self.assertFalse(c.unsaved())
                if suffix == ".json":
                    self.assertEqual(len(json.loads(original)["segments"]), 2)
                else:
                    self.assertEqual(len(list(csv.DictReader(original.decode().splitlines()))), 2)
                c.export(path)
                self.assertNotEqual(path.read_bytes(), original)

        c.switch("alpha")
        first = c.calibrate(0, 0, 1000, 6)
        c.save_calibration(self.path)
        original = self.path.read_bytes()
        second = c.calibrate(0, 0, 1000, 5)
        with patch("nuclemu.results.NamedTemporaryFile", side_effect=fail_during_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                c.save_calibration(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn("mca", c.lab.saved_calibrations)
        self.assertEqual(first.load(self.path), first)
        c.save_calibration(self.path)
        self.assertEqual(first.load(self.path), second)

    def test_failed_replace_of_new_file_does_not_mark_it_saved(self):
        with patch.object(Path, "replace", side_effect=PermissionError("file locked")):
            with self.assertRaisesRegex(PermissionError, "file locked"):
                self.c.export(self.path, all_segments=True)
        self.assertEqual(list(self.path.parent.iterdir()), [])
        self.assertTrue(self.c.unsaved())

    def test_cross_experiment_overwrite_invalidates_old_experiment(self):
        c = self.c
        c.export(self.path, all_segments=True)
        self.assertFalse(c.unsaved())
        c.switch("alpha")
        c.set_output("alpha_detector", True)
        c.start(1)
        c.advance(1)
        c.export(self.path)
        self.assertFalse(c.unsaved())
        c.switch("beta")
        self.assertTrue(c.unsaved())

    def test_same_file_cannot_preserve_two_device_exports(self):
        definition = Experiment("two", "Two counters", "", (),
            (Device("left", "counter", "Counter"), Device("right", "counter", "Counter")),
            lambda settings, start, end, rng: {"left": [2], "right": [5]})
        c = Workbench(definitions={"two": definition})
        c.start(1)
        c.advance(1)
        c.export(self.path)
        c.bind_device("right")
        c.export(self.path)
        self.assertTrue(c.unsaved())
        self.assertEqual(c.lab.saved, {(0, "right"): 1})

    def test_old_partial_copy_does_not_cover_new_exposure_and_no_external_polling(self):
        c = self.c
        c.clear(device="counter")
        c.configure_acquisition(device="counter", duration_s=None)
        c.start(device="counter")
        c.advance(1)
        c.export(self.path, all_segments=True)
        c.advance(1)
        newer = self.path.with_name("newer.json")
        c.export(newer, all_segments=True)
        self.assertFalse(c.unsaved())
        c.stop()
        c.switch("alpha")
        c.calibrate(0, 0, 1000, 6)
        c.save_calibration(newer)  # Leaves only the earlier beta snapshot.
        c.switch("beta")
        self.assertTrue(c.unsaved())
        c.export(self.path, all_segments=True)
        self.path.write_text("external edit", encoding="utf-8")
        # We track this workbench's saves, not filesystem history or external tools.
        with patch.object(Path, "stat", side_effect=AssertionError("Unexpected filesystem polling")):
            self.assertFalse(c.unsaved())

    def test_calibration_overwrite_and_independent_copies(self):
        c = self.c
        c.switch("alpha")
        first = c.calibrate(0, 0, 1000, 6)
        c.save_calibration(self.path)
        copy = self.path.with_name("energy-copy.json")
        c.save_calibration(copy)
        second = c.calibrate(0, 0, 1000, 5)
        c.save_calibration(self.path)
        self.assertEqual(c.lab.saved_calibrations["mca"], second)
        c.calibrate(0, 0, 1000, 6)
        self.assertEqual(c.lab.saved_calibrations["mca"], first)
        c.switch("beta")
        c.export(copy, all_segments=True)
        c.switch("alpha")
        self.assertNotIn("mca", c.lab.saved_calibrations)
        c.load_calibration(self.path)
        self.assertEqual(c.lab.saved_calibrations["mca"], second)
        c.switch("beta")
        c.export(self.path, all_segments=True)
        c.switch("alpha")
        self.assertNotIn("mca", c.lab.saved_calibrations)

    def test_measurement_and_calibration_replace_each_others_file_coverage(self):
        c = self.c
        c.switch("alpha")
        c.set_output("alpha_detector", True)
        c.start(1)
        c.advance(1)
        c.calibrate(0, 0, 1000, 6)
        c.export(self.path)
        self.assertFalse(c.unsaved())
        self.assertIn("mca", c.lab.saved_calibrations)
        c.save_calibration(self.path)
        self.assertTrue(c.unsaved())
        self.assertIn("mca", c.lab.saved_calibrations)
        c.export(self.path.with_suffix(".csv"))
        c.switch("beta")
        c.export(self.path)
        c.switch("alpha")
        self.assertFalse(c.unsaved())
        self.assertNotIn("mca", c.lab.saved_calibrations)


if __name__ == "__main__":
    unittest.main()
