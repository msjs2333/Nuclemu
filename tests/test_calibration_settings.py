import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from nuclemu.workbench import Workbench


PLUGIN = """\
from nuclemu.core import Device, Experiment, Parameter

def measure(settings, start, end, rng):
    counts = [0] * 4
    counts[settings["gain"]] = 1
    return {"mca": counts}

EXPERIMENT = Experiment(
    "gainlab", "Adjustable gain", "",
    (Parameter("gain", "Gain", "", 1, 1, 2, True),
     Parameter("foil", "Foil", "", 0, 0, 1, True)),
    (Device("mca", "spectrum", "MCA", 4, calibration_parameters=("gain",)),),
    measure,
)
"""


class CalibrationSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        (self.folder / "lab.py").write_text(PLUGIN, encoding="utf-8")
        self.lab = Workbench(paths=[self.folder])
        self.lab.switch("gainlab")
        for gain in (1, 2):
            self.lab.configure({"gain": gain})
            self.lab.start(1)
            self.lab.advance(1)
        self.lab.select(0)  # Current gain is 2, selected acquisition used gain 1.
        self.calibration = self.lab.calibrate(0, 0, 3, 3)
        self.path = self.folder / "energy.json"
        self.lab.save_calibration(self.path)

    def test_cli_roi_and_segment_exports_respect_only_declared_settings(self):
        csv_path = self.folder / "mixed.csv"
        json_path = self.folder / "mixed.json"
        run = subprocess.run([
            sys.executable, "-m", "nuclemu", "run", "gainlab", "--path", str(self.folder),
            "--step", "1,gain=1", "--step", "1,gain=2", "--step", "1,gain=1,foil=1",
            "--roi", "0:3", "--calibration", str(self.path),
            "--output", str(csv_path), "--output", str(json_path),
        ], capture_output=True, encoding="utf-8", check=True)
        self.assertEqual(run.stdout.count("energy=1 MeV"), 2)
        self.assertNotIn("energy=2", run.stdout)
        self.assertEqual(run.stdout.count("channel axis retained"), 1)
        with csv_path.open(encoding="utf-8", newline="") as stream:
            peaks = [row for row in csv.DictReader(stream) if row["counts"] == "1"]
        self.assertEqual([(p["channel"], p["energy_MeV"]) for p in peaks],
                         [("1", "1.0"), ("2", ""), ("1", "1.0")])
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertNotIn("calibration", data)
        self.assertEqual(data["conditional_calibration"]["conditions"], {"gain": 1})
        self.assertEqual([s["settings"]["gain"] for s in data["segments"]], [1, 2, 1])

    def test_history_switch_restores_applicable_energy_calibration(self):
        for index, energy in [(0, 1), (1, None), (0, 1)]:
            self.lab.select(index)
            self.assertEqual(self.lab.readout()["energy_MeV"], energy)
            self.assertEqual(self.lab.active_calibration() is not None, energy is not None)
        self.lab.select(1)
        with self.assertRaisesRegex(ValueError, "selected spectrum"):
            self.lab.load_calibration(self.path)

    def test_legacy_fixed_gain_file_still_loads_for_alpha(self):
        data = {"format": "nuclemu.calibration/1", "unit": "MeV", "experiment": "alpha",
                "device": "mca", "channels": 1024, "channel1": 0, "energy1": 0,
                "channel2": 1000, "energy2": 6}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.lab.switch("alpha")
        self.lab.load_calibration(self.path)
        self.assertEqual(self.lab.active_calibration().energy(1000), 6)
        data.update(experiment="gainlab", channels=4, channel2=3)
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.lab.switch("gainlab")
        with self.assertRaisesRegex(ValueError, "calibration parameters"):
            self.lab.load_calibration(self.path)
