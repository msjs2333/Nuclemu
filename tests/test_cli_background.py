"""CLI background choices survive portable export as measurement identities."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from nuclemu.exchange import load_package, save_package
from nuclemu.results import net_count_rate


ROOT = Path(__file__).resolve().parents[1]


class CliBackgroundTests(unittest.TestCase):
    def run_package(self, path, steps, background=None):
        arguments = [sys.executable, "-m", "nuclemu", "run", "beta",
                     "--seed", "42", "--device", "counter",
                     "--enable-output", "beta_detector", "--set", "foil_spec_um=100"]
        for step in steps:
            arguments.extend(("--step", step))
        if background is not None:
            arguments.extend(("--background", str(background)))
        arguments.extend(("--package", str(path)))
        result = subprocess.run(arguments, cwd=ROOT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return load_package(path), result.stdout

    def measurement(self, document, acquisition):
        matches = [item for item in document["items"] if item["kind"] == "measurement"
                   and item["document"]["snapshot"]["acquisition"] == acquisition]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def reading(self, item):
        product = item["document"]
        counts = [count for segment in product["segments"]
                  for count in segment["readings"]["counter"]]
        self.assertTrue(all(type(count) is int for count in counts))
        exposure = product["snapshot"]["exposure_s"]
        self.assertEqual(exposure, sum(segment["end_s"] - segment["start_s"]
                                      for segment in product["segments"]))
        return sum(counts), exposure

    def assert_background(self, document, item):
        identity = document.get("analysis", {}).get("counter", {}).get("background")
        self.assertEqual(identity, item["id"])
        self.assertEqual(str(UUID(identity)), identity)

    def test_background_first_reopens_with_raw_counts_and_unequal_exposures(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "beta.nuclemu"
            document, output = self.run_package(path, (
                "1.25,source_present=0", "2.5,source_present=1,foil_count=4"), 1)
            background = self.measurement(document, 1)
            sample = self.measurement(document, 2)
            self.assertEqual(self.reading(background), (61, 1.25))
            self.assertEqual(self.reading(sample), (3774, 2.5))
            self.assert_background(document, background)
            self.assertEqual(document["analysis"]["counter"]["selected"], sample["id"])
            # Reopen bytes independently; no live session or CLI summary is needed.
            reopened = load_package(path.read_bytes())
            reference = reopened["analysis"]["counter"]["background"]
            cached = next(item for item in reopened["items"] if item["id"] == reference)
            rate, uncertainty = net_count_rate(*self.reading(self.measurement(reopened, 2)),
                                              *self.reading(cached))
            self.assertEqual(rate, 1460.8)
            self.assertAlmostEqual(uncertainty, (3774/2.5**2+61/1.25**2)**.5)
            self.assertIn(f"net={rate:.6g} +/- {uncertainty:.6g}", output)

    def test_background_second_uses_its_measurement_identity(self):
        with TemporaryDirectory() as temporary:
            document, output = self.run_package(Path(temporary) / "later.nuclemu", (
                "2.5,source_present=1,foil_count=4", "1.25,source_present=0"), 2)
            background = self.measurement(document, 2)
            sample = self.measurement(document, 1)
            self.assertEqual(self.reading(background)[1], 1.25)
            self.assertEqual(self.reading(sample)[1], 2.5)
            self.assert_background(document, background)
            self.assertEqual(document["analysis"]["counter"]["selected"], sample["id"])
            rate, uncertainty = net_count_rate(*self.reading(sample), *self.reading(background))
            self.assertIn(f"net={rate:.6g} +/- {uncertainty:.6g}", output)

    def test_same_named_measurements_keep_background_after_reordering(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "same-name.nuclemu"
            document, _ = self.run_package(path, (
                "1.25,source_present=1,foil_count=4", "1.25,source_present=0"), 2)
            background = self.measurement(document, 2)
            sample = self.measurement(document, 1)
            background['title'] = sample['title'] = 'same name'
            self.assertEqual(background["title"], sample["title"])
            self.assertNotEqual(background["id"], sample["id"])
            self.assert_background(document, background)
            document["items"].reverse()
            save_package(path, document)
            reopened = load_package(path)
            self.assert_background(reopened, self.measurement(reopened, 2))
            self.assertEqual(self.reading(self.measurement(reopened, 1)), self.reading(sample))
            self.assertEqual(self.reading(self.measurement(reopened, 2)), self.reading(background))

    def test_without_background_option_does_not_invent_reference(self):
        with TemporaryDirectory() as temporary:
            document, output = self.run_package(Path(temporary) / "raw.nuclemu", (
                "1.25,source_present=0", "2.5,source_present=1,foil_count=4"))
            self.assertIsNone(document.get("analysis", {}).get("counter", {}).get("background"))
            self.assertEqual(self.reading(self.measurement(document, 1)), (61, 1.25))
            self.assertEqual(self.reading(self.measurement(document, 2)), (3774, 2.5))
            self.assertNotIn("net=", output)


if __name__ == "__main__":
    unittest.main()
