"""Exercise the same operations in a headless controller and real Tk widgets."""

import csv
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.core import Device, Experiment, Session
from nuclemu.gui import TkWorkbench, Workbench
from nuclemu.results import collect, net_count_rate


class WorkbenchTests(unittest.TestCase):
    def test_beta_reference_reading_background_export_and_repeated_display(self):
        c = Workbench(seed=42)
        c.switch("beta")
        c.configure({"source_present": "0"})
        c.start(1.25)
        c.advance(1.25)
        c.configure({"source_present": "1", "foil_count": "4"})
        c.start(2.5)
        for _ in range(25):
            c.advance(.1)
            c.readout()
        c.set_background(0)
        self.assertEqual([s["readings"]["counter"] for s in c.product()["segments"]], [[1], [122]])
        reading = c.readout()
        self.assertEqual(reading["exposure_s"], 2.5)
        self.assertEqual((reading["net_rate"], reading["uncertainty"]), net_count_rate(122, 2.5, 1, 1.25))
        records = list(c.session.records)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "beta.json"
            c.export(path, all_segments=True)
            self.assertFalse(c.unsaved())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), c.product())
            c.select(0)
            self.assertTrue(c.readout()["background_reference"])
            c.export(path.with_suffix(".csv"))
            with path.with_suffix(".csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["counts"], "1")
        for _ in range(10):
            c.product()
            c.readout()
        self.assertEqual(records, c.session.records)

    def test_alpha_reference_roi_and_bound_calibration_round_trip(self):
        c = Workbench(seed=187)
        c.switch("alpha")
        c.start()
        c.advance(2.25)
        c.stop()
        c.configure({"foil_um": "5"})
        c.start(1.25)
        c.advance(1.25)
        spectra = [s["readings"]["mca"] for s in c.product()["segments"]]
        self.assertEqual(list(map(sum, spectra)), [172, 92])
        self.assertEqual(c.readout(0, 1)["centroid"], None)
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
            self.assertEqual(sum(int(r["counts"]) for r in rows), 264)
            self.assertEqual(rows[1000]["energy_MeV"], "6.0")
            c.switch("beta")
            with self.assertRaises(ValueError):
                c.load_calibration(path)

    def test_pause_speed_stop_and_switch_preserve_unsaved_partial_exposure(self):
        c = Workbench(seed=187)
        c.start()
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
        c.start(.25)
        c.advance(.125)
        self.assertEqual(len(c.product()["segments"]), 2)
        for value in (0, -1, "nan", "inf"):
            with self.assertRaises(ValueError):
                c.set_speed(value)

    def test_invalid_parameter_form_is_atomic_and_does_not_close_window(self):
        c = Workbench()
        c.switch("beta")
        c.start()
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
            if experiment == "beta":
                c.configure({"source_present": 0})
                reference.set("source_present", 0)
            c.start(first)
            reference.start(first)
            reference.advance(first)
            for _ in range(int(first / .05)):
                c.advance(.05)
                c.product()
            c.configure(setting)
            for key, value in setting.items():
                reference.set(key, value)
            c.start(second)
            reference.start(second)
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
        for _ in range(2):
            self.c.start(1)
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
        c.start()
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


class TkWorkbenchTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError as error:
            self.skipTest(str(error))
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.now = 0.0
        self.c = Workbench(seed=42)
        self.ui = TkWorkbench(self.root, self.c, clock=lambda: self.now)
        self.addCleanup(self.destroy_window)
        self.root.update()

    def destroy_window(self):
        if self.ui.after_id is not None:
            self.root.after_cancel(self.ui.after_id)
        self.root.destroy()

    def test_real_window_timed_controls_background_selection_and_export(self):
        ui, c = self.ui, self.c
        ui.experiment_box.current(ui.experiment_ids.index("beta"))
        ui.change_experiment()
        ui.parameter_vars["source_present"].set("0")
        ui.mode.set("定时")
        ui.duration.set("1.25")
        ui.start_button.invoke()
        self.now += 1.25
        ui.tick()
        self.assertFalse(c.session.running)
        ui.parameter_vars["source_present"].set("1")
        ui.parameter_vars["foil_count"].set("4")
        ui.duration.set("2.5")
        ui.start_button.invoke()
        self.now += 2.5
        ui.tick()
        ui.background_box.current(1)
        ui.change_background()
        self.root.update()
        self.assertIn("48", ui.reading.get())
        self.assertIn("净计数率", ui.reading.get())
        self.assertEqual(ui.history.size(), 2)
        self.assertEqual(ui.counter_table.get_children(), ("0", "1"))
        first = ui.counter_table.item("0", "values")
        second = ui.counter_table.item("1", "values")
        self.assertEqual(first[2:], ("1", "1.25", "0.8"))
        self.assertEqual(second[2:], ("122", "2.5", "48.8"))
        self.assertIn("'foil_count': 4", second[1])
        ui.counter_table.selection_set("0")
        ui.select_counter_row()
        self.assertTrue(c.readout()["background_reference"])
        ui.follow_latest()
        ui.refresh()
        with TemporaryDirectory() as directory, patch("tkinter.filedialog.asksaveasfilename", return_value=str(Path(directory) / "selected.json")):
            ui.export()
            self.assertEqual(len(json.loads((Path(directory) / "selected.json").read_text(encoding="utf-8"))["segments"]), 1)
        with patch("tkinter.messagebox.askokcancel") as prompt:
            ui.experiment_box.current(ui.experiment_ids.index("alpha"))
            ui.change_experiment()
            prompt.assert_not_called()
        self.assertIn("foil_um", ui.parameter_vars)
        self.assertTrue(ui.spectrum_tools.winfo_manager())
        self.assertEqual(c.labs["beta"].view.product()["segments"][1]["readings"]["counter"], [122])

    def test_real_controls_pause_manual_stop_and_cancel_close(self):
        ui, c = self.ui, self.c
        ui.start_button.invoke()
        self.now = .25
        ui.pause.set(True)
        ui.change_pause()
        self.now = 5
        ui.tick()
        self.assertEqual(c.session.time_s, .25)
        ui.stop_button.invoke()
        with patch("tkinter.messagebox.askokcancel", return_value=False):
            ui.close()
        self.assertTrue(self.root.winfo_exists())
        self.assertFalse(c.session.running)

    def test_cancel_close_preserves_timed_gate_and_freezes_nested_dialog_time(self):
        ui, c = self.ui, self.c
        ui.mode.set("定时")
        ui.duration.set("2.25")
        ui.start_button.invoke()
        self.now = .5

        def cancel(*args, **kwargs):
            self.assertIn("采集中", args[1])
            self.now = 30
            ui.tick()  # Modal dialogs can run a nested Tk event loop.
            self.assertEqual(c.session.time_s, .5)
            self.assertTrue(c.session.running)
            return False

        with patch("tkinter.messagebox.askokcancel", side_effect=cancel):
            ui.close()
        self.assertTrue(c.session.running)
        self.assertEqual(c.session.records, [])
        self.assertFalse(c.paused)
        self.now = 31.75
        ui.tick()
        self.assertFalse(c.session.running)
        reference = Session(c.session.experiment, c.seed)
        reference.start(2.25)
        reference.advance(2.25)
        self.assertEqual(c.session.records, reference.records)

    def test_pause_is_independent_of_empty_or_invalid_speed_edit(self):
        ui, c = self.ui, self.c
        ui.start_button.invoke()
        for text in ("", "nan", "abc"):
            ui.speed.set(text)
            self.now += .25
            ui.pause_button.invoke()
            before = c.session.time_s
            self.assertTrue(c.paused)
            self.now += 10
            ui.tick()
            self.assertEqual(c.session.time_s, before)
            ui.pause_button.invoke()
            self.assertFalse(c.paused)
        self.assertEqual(c.speed, 1)
        ui.speed.set("2")
        ui.change_clock()
        before = c.session.time_s
        self.now += .25
        ui.tick()
        self.assertEqual(c.session.time_s, before + .5)

    def test_new_calibration_after_old_export_prompts_and_save_clears_warning(self):
        ui, c = self.ui, self.c
        c.start(1)
        c.advance(1)
        with TemporaryDirectory() as directory:
            c.export(Path(directory) / "old-spectrum.json")
            self.assertFalse(c.unsaved())
            for variable, value in zip(ui.calibration_vars, (0, 0, 1000, 6)):
                variable.set(str(value))
            ui.apply_calibration()
            with patch("tkinter.messagebox.askokcancel", return_value=False) as prompt:
                ui.close()
                self.assertIn("未保存刻度", prompt.call_args.args[1])
            # CSV energies are not a persisted calibration definition.
            c.export(Path(directory) / "calibrated.csv")
            with patch("tkinter.messagebox.askokcancel", return_value=False) as prompt:
                ui.close()
                self.assertIn("未保存刻度", prompt.call_args.args[1])
            with patch("tkinter.filedialog.asksaveasfilename", return_value=str(Path(directory) / "energy.json")):
                ui.save_calibration()
            with patch("tkinter.messagebox.askokcancel") as prompt, patch.object(self.root, "destroy") as destroy:
                ui.close()
                prompt.assert_not_called()
                destroy.assert_called_once()

    def test_file_dialog_freezes_time_and_json_preserves_calibration(self):
        ui, c = self.ui, self.c
        c.calibrate(0, 0, 1000, 6)
        c.start(1.25)
        self.now = 1
        ui.tick()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"

            def pick_file(**kwargs):
                self.now = 20
                ui.tick()
                return str(path)

            with patch("tkinter.filedialog.asksaveasfilename", side_effect=pick_file):
                ui.export()
            self.assertEqual(c.session.time_s, 1)
            self.assertTrue(c.session.running)
            self.assertEqual(c.lab.saved_calibrations["mca"], c.lab.calibrations["mca"])
            self.now = 20.25
            ui.tick()
            self.assertFalse(c.session.running)
            self.assertEqual(c.readout()["exposure_s"], 1.25)

    def test_close_warns_after_same_file_loses_an_exported_segment(self):
        ui, c = self.ui, self.c
        c.switch("beta")
        ui.rebuild()
        for _ in range(2):
            c.start(1)
            c.advance(1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "reused.json"
            c.select(0)
            c.export(path)
            c.select(1)
            c.export(path)
            with patch("tkinter.messagebox.askokcancel", return_value=False) as prompt:
                ui.close()
                self.assertIn("未导出读数", prompt.call_args.args[1])
            self.assertTrue(self.root.winfo_exists())

    def test_uncommitted_roi_input_does_not_pause_acquisition_and_axis_preserves_calibration(self):
        ui, c = self.ui, self.c
        ui.roi_first.set("")
        ui.start_button.invoke()
        self.now = 1
        ui.tick()
        self.assertFalse(c.paused)
        self.assertEqual(len(c.session.records), 1)
        with self.assertRaises(ValueError):
            ui.apply_roi()
        self.assertEqual(ui.roi, (0, 1023))
        ui.roi_first.set("850")
        ui.roi_last.set("870")
        ui.apply_roi()
        calibration = c.calibrate(0, 0, 1000, 6)
        ui.draw()
        self.assertIn("能量 / MeV", [ui.canvas.itemcget(i, "text") for i in ui.canvas.find_all() if ui.canvas.type(i) == "text"])
        ui.energy_axis.set(False)
        ui.draw()
        self.assertIn("道号", [ui.canvas.itemcget(i, "text") for i in ui.canvas.find_all() if ui.canvas.type(i) == "text"])
        self.assertIs(c.lab.calibrations[c.device.id], calibration)

    def test_real_calibration_save_load_and_history_selection(self):
        ui, c = self.ui, self.c
        ui.start_button.invoke()
        self.now = 2.25
        ui.stop_button.invoke()
        ui.parameter_vars["foil_um"].set("5")
        ui.duration.set("1.25")
        ui.mode.set("定时")
        ui.start_button.invoke()
        self.now += 1.25
        ui.tick()
        ui.history.selection_clear(0, "end")
        ui.history.selection_set(0)
        ui.select_history()
        self.assertEqual(c.lab.selected, 0)
        self.assertEqual(c.segment()["settings"]["foil_um"], 0)
        for variable, value in zip(ui.calibration_vars, (0, 0, 1000, 6)):
            variable.set(str(value))
        ui.apply_calibration()
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "energy.json")
            with patch("tkinter.filedialog.asksaveasfilename", return_value=path):
                ui.save_calibration()
            c.lab.calibrations.clear()
            with patch("tkinter.filedialog.askopenfilename", return_value=path):
                ui.load_calibration()
            self.assertEqual(c.lab.calibrations["mca"].energy(1000), 6)
        self.root.update()
        ui.follow_latest()
        ui.refresh()
        self.assertEqual(c.segment()["settings"]["foil_um"], 5)


if __name__ == "__main__":
    unittest.main()
