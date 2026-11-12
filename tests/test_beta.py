"""Acceptance checks for the beta counter and its measured quantities."""

import csv
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from random import Random
from statistics import mean, variance

from nuclemu.core import Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT, sample_counts
from nuclemu.results import collect, net_count_rate, save_product


def session_for_counter(seed):
    session = Session(EXPERIMENT, seed=seed)
    session.set_output(DETECTOR_OUTPUT, True)
    return session


class BetaAbsorptionTests(unittest.TestCase):
    def test_observed_rate_matches_reference_at_several_thicknesses(self):
        for count, expected_cps in ((0, 102.0), (4, 53.25), (8, 28.27), (16, 8.90)):
            with self.subTest(foil_count=count):
                settings = {"source_present": 1, "foil_count": count}
                rng = Random(123)
                windows = [sample_counts(settings, 0, 1, rng)[DETECTOR_OUTPUT][0] for _ in range(4096)]
                self.assertAlmostEqual(mean(windows), expected_cps, delta=5 * math.sqrt(expected_cps / len(windows)))
                self.assertAlmostEqual(variance(windows), expected_cps, delta=0.12 * expected_cps)

    def test_background_ignores_foil_stack(self):
        for foil_count in (0, 24):
            rng = Random(82)
            samples = [
                sample_counts({"source_present": 0, "foil_count": foil_count}, 0, 10, rng)[DETECTOR_OUTPUT][0]
                for _ in range(2000)
            ]
            self.assertAlmostEqual(mean(samples), 20, delta=0.5)

    def test_acquire_background_then_sample_with_different_exposures(self):
        session = session_for_counter(42)
        session.set("source_present", 0)
        session.start(device="counter")
        session.advance(19.5)
        session.stop(device="counter")
        next_row = len(session.records)
        session.set("source_present", 1)
        session.set("foil_count", 4)
        session.start(device="counter")
        session.advance(7.25)
        session.stop(device="counter")
        background = session.records[:next_row]
        sample = session.records[next_row:]
        self.assertTrue(all(row.settings["source_present"] == 0 for row in background))
        self.assertTrue(all(row.settings["foil_count"] == 4 for row in sample))
        tb = sum(row.exposure_s for row in background)
        ts = sum(row.exposure_s for row in sample)
        self.assertEqual((tb, ts), (19.5, 7.25))
        nb = sum(row.readings["counter"][0] for row in background)
        ns = sum(row.readings["counter"][0] for row in sample)
        rate, standard_error = net_count_rate(ns, ts, nb, tb)
        self.assertAlmostEqual(rate, ns / ts - nb / tb)
        self.assertAlmostEqual(standard_error, math.sqrt(ns / ts**2 + nb / tb**2))

    def test_absorption_curve_exports_preserve_counts_exposure_and_conditions(self):
        session = session_for_counter(53)
        conditions = ((0, 0, 60), (1, 0, 20), (1, 4, 7.25),
                      (1, 8, 19.5), (1, 16, 30), (1, 24, 40))
        totals = []
        for source_present, foil_count, duration in conditions:
            session.set("source_present", source_present)
            session.set("foil_count", foil_count)
            first = len(session.records)
            session.start(device="counter")
            session.advance(duration)
            session.stop(device="counter")
            totals.append(sum(row.readings["counter"][0] for row in session.records[first:]))

        product = collect(EXPERIMENT, session.records, seed=53)
        with TemporaryDirectory() as directory:
            json_path = Path(directory) / "beta.json"
            csv_path = Path(directory) / "beta.csv"
            save_product(json_path, product, device="counter")
            save_product(csv_path, product, device="counter")
            exported = json.loads(json_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))

        self.assertEqual(exported["experiment"], "beta")
        self.assertEqual(exported["devices"], {"counter": {"kind": "counter", "channels": 1}})
        self.assertEqual(len(exported["segments"]), len(conditions))
        self.assertEqual(len(rows), len(conditions))
        for segment, row, (source, foils, exposure), count in zip(
            exported["segments"], rows, conditions, totals
        ):
            settings = {"source_present": source, "foil_count": foils, "foil_spec_um": 100}
            self.assertEqual(segment["settings"], settings)
            self.assertEqual(segment["readings"], {"counter": [count]})
            self.assertEqual(segment["end_s"] - segment["start_s"], exposure)
            self.assertEqual(json.loads(row["settings"]), settings)
            self.assertEqual((row["experiment"], row["device"], row["channel"]),
                             ("beta", "counter", "0"))
            self.assertEqual(row["energy_MeV"], "")
            self.assertEqual(float(row["exposure_s"]), exposure)
            self.assertEqual(float(row["end_s"]) - float(row["start_s"]), exposure)
            self.assertEqual(int(row["counts"]), count)
            if source:
                rate, error = net_count_rate(int(row["counts"]), float(row["exposure_s"]),
                                            int(rows[0]["counts"]), float(rows[0]["exposure_s"]))
                self.assertAlmostEqual(rate, count / exposure - totals[0] / 60)
                self.assertAlmostEqual(error, math.sqrt(count / exposure**2 + totals[0] / 60**2))

    def test_zero_counts_and_negative_net_rate_are_valid_measurements(self):
        session = session_for_counter(42)
        session.set("source_present", 0)
        session.start(device="counter")
        session.advance(0.001)
        session.stop(device="counter")
        row = session.records[0]
        self.assertEqual(row.readings["counter"], (0,))
        self.assertEqual(net_count_rate(0, row.exposure_s, 0, 60), (0, 0))
        rate, error = net_count_rate(0, row.exposure_s, 120, 60)
        self.assertEqual(rate, -2)
        self.assertAlmostEqual(error, math.sqrt(120) / 60)


if __name__ == "__main__":
    unittest.main()
