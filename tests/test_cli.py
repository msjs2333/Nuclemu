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
        for expected in ("alpha:", "beta:", "foil_um", "µm", "spectrum:mca", "counter:counter"):
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
                "--step", "1.25,source_present=0", "--step", "2.5,source_present=1,foil_count=4",
                "--background", "1", "--output", str(target / "beta.json"),
                "--output", str(target / "beta.csv"))
            product = json.loads((target / "beta.json").read_text(encoding="utf-8"))
            session = Session(discover()["beta"], seed=42)
            session.set("source_present", 0)
            session.start(1.25)
            session.advance(1.25)
            session.set("source_present", 1)
            session.set("foil_count", 4)
            session.start(2.5)
            session.advance(2.5)
            self.assertEqual(product, MeasurementView(session, 42).product())
            self.assertEqual([s["readings"]["counter"][0] for s in product["segments"]], [1, 122])
            self.assertIn("net=48", output)
            with (target / "beta.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([float(row["exposure_s"]) for row in rows], [1.25, 2.5])
            self.assertEqual([int(row["counts"]) for row in rows], [1, 122])

    def test_alpha_reference_then_foil_roi_calibration_export(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            calibration = Calibration("alpha", "mca", 1024, 0, 0, 1000, 6)
            calibration.save(target / "cal.json")
            arguments = ("run", "alpha", "--seed", "187", "--device", "spectrum:mca",
                "--step", "2.25,foil_um=0", "--step", "1.25,foil_um=5", "--roi", "830:890",
                "--calibration", str(target / "cal.json"))
            summary = self.ok(*arguments, "--output", str(target / "alpha.json"),
                              "--output", str(target / "alpha.csv"))
            product = json.loads((target / "alpha.json").read_text(encoding="utf-8"))
            session = Session(discover()["alpha"], seed=187)
            session.start(2.25)
            session.advance(2.25)
            session.set("foil_um", 5)
            session.start(1.25)
            session.advance(1.25)
            expected = MeasurementView(session, 187).product()
            self.assertEqual(product["segments"], expected["segments"])
            self.assertEqual([sum(s["readings"]["mca"]) for s in product["segments"]], [172, 92])
            self.assertIn("centroid=859.134", summary)
            self.assertIn("energy=", summary)
            with (target / "alpha.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2048)
            self.assertEqual(float(rows[1000]["energy_MeV"]), 6)
            self.assertEqual(sum(int(row["counts"]) for row in rows), 264)
            self.assertEqual(self.ok(*arguments), summary.split("saved ")[0])
            self.assertIn("centroid=None", self.ok("run", "alpha", "--duration", "0.25", "--roi", "0:20"))

    def test_repeated_unchanged_gates_remain_independent(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            self.ok("run", "beta", "--step", "0.25", "--step", "0.25", "--output", str(path))
            product = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(product["segments"]), 2)
            self.assertEqual([s["end_s"] - s["start_s"] for s in product["segments"]], [0.25, 0.25])

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
        # No Tk import is needed to parse or run CLI commands.
        result = subprocess.run([sys.executable, "-c",
            "import sys; from nuclemu.cli import main; main(['list']); "
            "assert 'tkinter' not in sys.modules; assert 'nuclemu.gui' not in sys.modules; "
            "assert 'nuclemu.web' not in sys.modules"], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        from nuclemu.cli import main
        import types
        fake = types.ModuleType("nuclemu.gui")
        fake.launch = unittest.mock.Mock()
        with patch.dict(sys.modules, {"nuclemu.gui": fake}):
            self.assertEqual(main(["--path", "one", "gui", "--path", "two"]), 0)
        fake.launch.assert_called_once_with(paths=["one", "two"])


if __name__ == "__main__":
    unittest.main()
