"""Exercise the actual module entry point and its measured products."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import describe, discover
from nuclemu.core import Session
from nuclemu.results import Calibration, MeasurementView


ROOT = Path(__file__).resolve().parents[1]


def invoke(*arguments):
    return subprocess.run([sys.executable, "-m", "nuclemu", *arguments], cwd=ROOT,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                          text=True, encoding="utf-8", capture_output=True)


class CliTests(unittest.TestCase):
    def ok(self, *arguments):
        result = invoke(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_discovery_units_devices_and_validation(self):
        output = self.ok("list")
        for expected in ("alpha:", "beta:", "foil_spec_um", "µm", "spectrum:mca", "counter:counter"):
            self.assertIn(expected, output)
        self.assertIn("valid alpha", self.ok("validate", "alpha"))

    def test_list_matches_workbench_apparatus_and_bindings(self):
        for name in ("alpha", "beta"):
            with self.subTest(experiment=name):
                definition = discover()[name]
                entry = describe(definition)
                output = self.ok("list", name)
                self.assertIn(f"question: {entry['question']}", output)
                for index, paragraph in enumerate(entry["guide"], 1):
                    self.assertIn(f"guide {index}: {paragraph}", output)
                devices = {d.id: d for d in definition.devices}
                for part in entry["components"]:
                    block = f"  component {part['kind']}:{part['id']}: {part['label']}\n"
                    if part["description"]:
                        block += f"    {part['description']}\n"
                    if part["parameters"]:
                        block += f"    parameters: {', '.join(part['parameters'])}\n"
                    if part["device"] is not None:
                        d = devices[part["device"]]
                        block += f"    device: {d.kind}:{d.id}\n"
                    self.assertIn(block, output)
                for link in entry["connections"]:
                    self.assertIn(f"connection {link['kind']}: {link['source']} -> {link['target']}; {link['label']}", output)

    def test_beta_background_then_sample_matches_session_and_csv(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            output = self.ok("run", "beta", "--seed", "42", "--device", "counter:counter",
                "--enable-output", "beta_detector",
                "--step", "1.25,source_present=0", "--step", "2.5,source_present=1,foil_count=4",
                "--background", "1", "--output", str(target / "beta.json"),
                "--output", str(target / "beta.csv"))
            product = json.loads((target / "beta.json").read_text(encoding="utf-8"))
            session = Session(discover()["beta"], seed=42)
            session.set_output("beta_detector", True)
            session.set("source_present", 0)
            session.start(1.25, device="counter")
            session.advance(1.25)
            session.set("source_present", 1)
            session.set("foil_count", 4)
            session.clear(device="counter")
            session.start(2.5, device="counter")
            session.advance(2.5)
            expected = dict(MeasurementView(session, 42).product())
            expected["devices"] = {"counter": expected["devices"]["counter"]}
            self.assertEqual(product, expected)
            self.assertEqual([s["readings"]["counter"][0] for s in product["segments"]], [61, 3774])
            self.assertIn("net=1460.8", output)
            with (target / "beta.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([float(row["exposure_s"]) for row in rows], [1.25, 2.5])
            self.assertEqual([int(row["counts"]) for row in rows], [61, 3774])

    def test_beta_each_selected_instrument_matches_its_own_plan(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            common = ("run", "beta", "--seed", "42", "--enable-output", "beta_detector",
                      "--set", "source_present=1", "--set", "foil_spec_um=100", "--set", "foil_count=4")
            self.ok(*common, "--device", "counter", "--step", "5", "--step", "5",
                    "--output", str(target / "short.json"))
            self.ok(*common, "--device", "counter_b", "--duration", "10",
                    "--output", str(target / "long.json"))
            short = json.loads((target / "short.json").read_text(encoding="utf-8"))["segments"]
            long = json.loads((target / "long.json").read_text(encoding="utf-8"))["segments"]
            # A and B now use separate repeated observations. Compare each real
            # command to the same selected device and gate plan, not to each other.
            for device, durations, actual in (("counter", (5, 5), short),
                                               ("counter_b", (10,), long)):
                reference = Session(discover()["beta"], seed=42)
                reference.configure({"source_present": 1, "foil_spec_um": 100, "foil_count": 4})
                reference.set_output("beta_detector", True)
                self.assertTrue(reference.output_enabled["beta_detector_b"])
                for index, duration in enumerate(durations):
                    if index:
                        reference.clear(device=device)
                    reference.start(duration, device=device)
                    reference.advance(duration)
                self.assertEqual(actual, MeasurementView(reference).product()["segments"])
            self.assertEqual(long[0]["acquisition"], 1)
            self.assertEqual(long[0]["end_s"]-long[0]["start_s"], 10)
            self.assertEqual([s["end_s"] - s["start_s"] for s in short], [5, 5])
            self.assertEqual([s["acquisition"] for s in short], [1, 2])

    def test_portable_package_inspection_item_export_and_same_name_import(self):
        from nuclemu.exchange import load_item, load_package
        from zipfile import ZipFile
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = directory / "beta.nuclemu"
            common = ("run", "beta", "--seed", "42", "--device", "counter",
                      "--enable-output", "beta_detector", "--step", "1.25,source_present=0",
                      "--step", "2.5,source_present=1,foil_count=4")
            self.ok(*common, "--package", str(package))
            with ZipFile(package) as archive:
                self.assertEqual(set(archive.namelist()), {"manifest.json", "experiment.sqlite3"})
            summary = json.loads(self.ok("files", "inspect", str(package)))
            self.assertEqual(len(summary["items"]), 2)
            identity = summary["items"][0]["id"]
            single = directory / "background.csv"
            self.ok("files", "export", str(package), "--item", identity, "--output", str(single))
            bundle = load_item(single)
            self.assertEqual(bundle["items"][0]["document"]["snapshot"]["exposure_s"], 1.25)
            merged = directory / "merged.nuclemu"
            self.ok("files", "import", str(package), str(single), "--item", identity, "--output", str(merged))
            original, copied = load_package(package), load_package(merged)
            self.assertEqual(len(original["items"]), 2)
            self.assertEqual(len(copied["items"]), 3)
            self.assertEqual(copied["items"][:2], original["items"])
            self.assertNotEqual(copied["items"][2]["id"], identity)
            for item in copied["items"]:
                self.assertIn(item["document"]["snapshot"]["exposure_s"], (1.25, 2.5))
            result = invoke(*common, "--package", str(package), "--output", str(package))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(load_package(package), original)

    def test_legacy_archive_conversion_entry_preserves_counts(self):
        from nuclemu.exchange import load_package
        from nuclemu.web_store import ArchiveStore
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            store = ArchiveStore(directory)
            document = dict(definition=dict(id="legacy", title="Legacy lab", description="",
                parameters=[], devices=[dict(id="m", kind="counter", label="M", channels=1)]),
                time_s=1, settings={}, device="m", analysis={}, calibrations={},
                product=dict(format="nuclemu.measurement/1", experiment="legacy", seed=42,
                    devices={"m": dict(kind="counter", channels=1)}, segments=[dict(acquisition=1,
                        start_s=0, end_s=1, settings={}, readings={"m": [7]})]))
            store.write("old", "archive", document)
            database = directory / "workbench.sqlite3"
            original = database.read_bytes()
            inspection = json.loads(self.ok("files", "inspect", str(database)))
            self.assertEqual(inspection["archives"][0]["id"], "old")
            output = directory / "converted.nuclemu"
            self.ok("files", "convert-archive", str(database), "--archive", "old", "--output", str(output))
            converted = load_package(output)
            self.assertEqual(converted["items"][0]["document"]["segments"][0]["readings"], {"m": [7]})
            self.assertEqual(database.read_bytes(), original)
            failed = invoke("files", "convert-archive", str(database), "--archive", "old", "--output", str(database))
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(database.read_bytes(), original)

    def test_alpha_reference_then_foil_roi_calibration_export(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            calibration = Calibration("alpha", "mca", 1024, 0, 0, 1000, 6)
            calibration.save(target / "cal.json")
            arguments = ("run", "alpha", "--seed", "187", "--device", "spectrum:mca",
                "--enable-output", "alpha_detector", "--set", "source_present=1",
                "--step", "2.25,foil_um=0", "--step", "1.25,foil_um=5", "--roi", "830:890",
                "--calibration", str(target / "cal.json"))
            summary = self.ok(*arguments, "--output", str(target / "alpha.json"),
                              "--output", str(target / "alpha.csv"))
            product = json.loads((target / "alpha.json").read_text(encoding="utf-8"))
            session = Session(discover()["alpha"], seed=187)
            session.set_output("alpha_detector", True)
            session.set("source_present", 1)
            session.start(2.25)
            session.advance(2.25)
            session.set("foil_um", 5)
            session.clear(device="mca")
            session.start(1.25)
            session.advance(1.25)
            expected = MeasurementView(session, 187).product()
            self.assertEqual(product["segments"], expected["segments"])
            self.assertEqual([sum(s["readings"]["mca"]) for s in product["segments"]], [172, 86])
            self.assertIn("centroid=859.134", summary)
            self.assertIn("energy=", summary)
            with (target / "alpha.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2048)
            self.assertEqual(float(rows[1000]["energy_MeV"]), 6)
            self.assertEqual(sum(int(row["counts"]) for row in rows), 258)
            self.assertEqual(self.ok(*arguments), summary.split("saved ")[0])
            self.assertIn("centroid=None", self.ok("run", "alpha", "--duration", "0.25", "--roi", "0:20"))

    def test_repeated_unchanged_gates_remain_independent(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            self.ok("run", "beta", "--device", "counter", "--step", "0.25", "--step", "0.25", "--output", str(path))
            product = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(product["segments"]), 2)
            self.assertEqual([s["end_s"] - s["start_s"] for s in product["segments"]], [0.25, 0.25])

    def test_alpha_legacy_foil_commands_match_explicit_specification(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            common = ("run", "alpha", "--seed", "187", "--device", "mca",
                      "--enable-output", "alpha_detector", "--set", "source_present=1")
            self.ok(*common, "--step", "2.25,foil_um=0", "--step", "1.25,foil_um=5",
                    "--output", str(target / "old.json"))
            self.ok(*common, "--step", "2.25,foil_spec_um=1,foil_count=0",
                    "--step", "1.25,foil_spec_um=1,foil_count=5", "--output", str(target / "new.json"))
            old = json.loads((target / "old.json").read_text(encoding="utf-8"))
            new = json.loads((target / "new.json").read_text(encoding="utf-8"))
            self.assertEqual(old, new)
            self.assertEqual([sum(s["readings"]["mca"]) for s in old["segments"]], [172, 86])
            for segment, count in zip(old["segments"], (0, 5)):
                self.assertNotIn("foil_um", segment["settings"])
                self.assertEqual(segment["settings"]["foil_spec_um"], 1)
                self.assertEqual(segment["settings"]["foil_count"], count)
            self.assertNotEqual(old["segments"][0]["acquisition"], old["segments"][1]["acquisition"])

    def test_alpha_migration_and_batch_ambiguity_leave_settings_unchanged(self):
        for options, message in (
            (("--set", "foil_um=2.5"), "迁移"),
            (("--set", "foil_um=5", "--set", "foil_count=5"), "歧义"),
            (("--set", "foil_spec_um=1", "--set", "foil_um=5"), "歧义")):
            with self.subTest(options=options):
                result = invoke("run", "alpha", "--duration", "1", *options)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertEqual(result.stdout, "")
        for step in ("1,foil_um=2.5", "1,foil_um=5,foil_count=5", "1,foil_count=5,foil_um=5"):
            result = invoke("run", "alpha", "--step", step)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
        session = Session(discover()["alpha"], seed=187)
        session.configure({"foil_spec_um": 2, "foil_count": 3})
        session.set_output("alpha_detector", True)
        session.start(5, device="mca")
        session.advance(.4)
        before = (dict(session.settings), list(session.records), session.instrument("mca"), session.time_s)
        for batch in ({"foil_um": 2.5}, {"foil_um": 5, "foil_count": 5}):
            with self.assertRaises(ValueError):
                session.configure(batch)
            self.assertEqual((dict(session.settings), list(session.records), session.instrument("mca"), session.time_s), before)

    def test_named_output_course_selects_instrument_and_preserves_product(self):
        course = ROOT / "examples" / "courses"
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            output = self.ok("run", "split-signal", "--path", str(course), "--seed", "187",
                "--device", "counter:b", "--enable-output", "detector", "--step", "1.25,rate=0",
                "--step", "2.5,rate=40", "--background", "1",
                "--output", str(target / "b.json"), "--output", str(target / "b.csv"))
            session = Session(discover([course])["split-signal"], seed=187)
            session.set_output("detector", True)
            for index, (duration, rate) in enumerate(((1.25, 0), (2.5, 40))):
                if index:
                    session.clear(device="b")
                session.set("rate", rate)
                session.start(duration, device="b")
                session.advance(duration)
            expected = dict(MeasurementView(session).product())
            expected["devices"] = {"b": expected["devices"]["b"]}
            product = json.loads((target / "b.json").read_text(encoding="utf-8"))
            self.assertEqual(product, expected)
            self.assertIn("detector output detector: on", output)
            self.assertNotIn("counter:a:", output)
            self.assertIn("net=", output)
            with (target / "b.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["device"] for row in rows], ["b", "b"])
            self.assertEqual([float(row["exposure_s"]) for row in rows], [1.25, 2.5])
            self.assertEqual([int(row["counts"]) for row in rows],
                             [s["readings"]["b"][0] for s in product["segments"]])

    def test_named_output_sparse_segments_and_explicit_zero_input(self):
        arguments = ("run", "split-signal", "--path", str(ROOT / "examples" / "courses"),
                     "--seed", "187", "--duration", "2.5")
        disabled = self.ok(*arguments)
        self.assertIn("detector output detector: off (zero input)", disabled)
        self.assertIn("counter:a: counts=0", disabled)
        self.assertIn("counter:b: counts=0", disabled)
        enabled = self.ok(*arguments, "--enable-output", "detector")
        self.assertIn("counter:a:", enabled)
        self.assertIn("counter:b:", enabled)
        self.assertNotIn("counts=0;", enabled)
        selected = self.ok(*arguments, "--device", "a")
        self.assertIn("1 segment(s)", selected)
        self.assertIn("counter:a: counts=0", selected)
        self.assertNotIn("counter:b:", selected)
        listing = self.ok("list", "split-signal", "--path", str(ROOT / "examples" / "courses"))
        self.assertIn("output detector:", listing)
        self.assertIn("input: detector", listing)
        for options in (("--enable-output", "missing"), ("--background", "1")):
            result = invoke(*arguments, *options)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    def test_output_cannot_overwrite_input_calibration_or_alias(self):
        with TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            source = directory / "calibration.json"
            Calibration("alpha", "mca", 1024, 0, 0, 1000, 6).save(source)
            original = source.read_bytes()
            normal = directory / "measurement.csv"
            (directory / "nested").mkdir()
            aliases = (str(source), os.path.relpath(source, ROOT),
                       str(directory / "nested" / ".." / source.name))
            for alias in aliases:
                with self.subTest(alias=alias):
                    result = invoke("run", "alpha", "--duration", "1", "--calibration", str(source),
                                    "--output", str(normal), "--output", alias)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("input calibration", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(normal.exists())
            self.ok("run", "alpha", "--duration", "1", "--calibration", str(source),
                    "--output", str(normal))
            self.assertTrue(normal.exists())
            self.assertEqual(source.read_bytes(), original)

    def test_output_cannot_overwrite_input_calibration_via_hardlink(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "calibration.json"
            Calibration("alpha", "mca", 1024, 0, 0, 1000, 6).save(source)
            original = source.read_bytes()
            hardlink = directory / "alias.json"
            try:
                os.link(source, hardlink)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"System temporary directory does not support hard links: {error}")
            normal = directory / "measurement.csv"
            result = invoke("run", "alpha", "--duration", "1", "--calibration", str(source),
                            "--output", str(normal), "--output", str(hardlink))
            self.assertEqual(result.returncode, 2)
            self.assertIn("input calibration", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(normal.exists())

    def test_external_directory_discovery_and_run(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "lab.py").write_text(
                "from nuclemu.core import Device, Experiment, Parameter\n"
                "EXPERIMENT = Experiment('local', 'Local lab', '', "
                "(Parameter('gain', 'Gain', 'V', 1, 0, 2),), "
                "(Device('left', 'counter', 'Left'), Device('right', 'counter', 'Right')), "
                "lambda settings, start, end, rng: {'left': [7], 'right': [9]})\n", encoding="utf-8")
            self.assertIn("local:", self.ok("--path", temporary, "list"))
            output = self.ok("list", "local", "--path", temporary)
            self.assertIn("component controls:controls: 实验参数\n    parameters: gain", output)
            self.assertIn("component instrument:device-left: Left\n    device: counter:left", output)
            self.assertIn("component instrument:device-right: Right\n    device: counter:right", output)
            self.assertIn("valid local", self.ok("validate", "--path", temporary))
            self.assertIn("counts=7", self.ok("run", "local", "--path", temporary,
                                            "--duration", "0.5", "--device", "counter:left"))
            result = invoke("run", "local", "--path", temporary, "--duration", "1", "--device", "counter")
            self.assertEqual(result.returncode, 2)
            self.assertIn("KIND:ID", result.stderr)

    def test_invalid_inputs_report_errors_without_tracebacks(self):
        for arguments in (("run", "missing", "--duration", "1"),
                ("run", "beta", "--duration", "nan"),
                ("run", "beta", "--duration", "-1"),
                ("run", "beta", "--step", "1,foil_count=0.5"),
                ("run", "beta", "--step", "1,no_such_parameter=2"),
                ("run", "beta", "--step", "1,bad"),
                ("run", "alpha", "--duration", "1", "--roi", "0:1024"),
                ("run", "beta", "--duration", "1", "--background", "2"),
                ("validate", "--path", "no-such-experiment-directory")):
            with self.subTest(arguments=arguments):
                result = invoke(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)

    def test_instance_id_takes_priority_over_another_device_kind(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "binding.py").write_text(
                "from nuclemu.core import Device, Experiment\n"
                "EXPERIMENT = Experiment('binding', 'Binding', '', (), "
                "(Device('s', 'spectrum', 'Spectrum', 8), Device('other', 's', 'Other')), "
                "lambda settings, start, end, rng: {'s': [0,2,0,0,0,0,0,0], 'other': [9]})\n",
                encoding="utf-8")
            Calibration("binding", "s", 8, 0, 0, 7, 7).save(path / "cal.json")
            output = self.ok("run", "binding", "--path", temporary, "--duration", "1",
                "--device", "s", "--calibration", str(path / "cal.json"), "--roi", "0:7",
                "--output", str(path / "product.json"))
            self.assertIn("energy=1 MeV", output)
            product = json.loads((path / "product.json").read_text(encoding="utf-8"))
            self.assertEqual(list(product["devices"]), ["s"])

    def test_console_main_and_lazy_gui_forward_paths(self):
        # Non-GUI commands do not import the browser workbench or its server.
        result = subprocess.run([sys.executable, "-c",
            "import sys; from nuclemu.cli import main; main(['list']); "
            "assert 'nuclemu.gui' not in sys.modules; "
            "assert 'nuclemu.web' not in sys.modules"], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        from nuclemu.cli import main
        import types
        fake = types.ModuleType("nuclemu.web")
        fake.launch = unittest.mock.Mock()
        with patch.dict(sys.modules, {"nuclemu.web": fake}):
            self.assertEqual(main(["--path", "one", "gui", "--path", "two"]), 0)
        fake.launch.assert_called_once_with(paths=["one", "two"])

    def test_python_gui_entry_forwards_to_web(self):
        from nuclemu.gui import Workbench, launch
        from nuclemu.workbench import Workbench as SharedWorkbench
        self.assertIs(Workbench, SharedWorkbench)
        with patch("nuclemu.web.launch") as launch_web:
            launch(paths=("course-labs",))
        launch_web.assert_called_once_with(paths=("course-labs",))


if __name__ == "__main__":
    unittest.main()
