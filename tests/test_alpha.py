"""Alpha spectroscopy acceptance checks using acquired channel histograms."""

import math
import unittest

from nuclemu.core import Session
from nuclemu.experiments.alpha import EXPERIMENT, transmitted_energy
from nuclemu.physics import AluminumFoil
from nuclemu.results import Calibration


def acquire(thickness_um, seconds=60, seed=187):
    session = Session(EXPERIMENT, seed=seed)
    session.set("foil_um", thickness_um)
    session.start()
    session.advance(seconds)
    session.stop()
    spectrum = [0] * 1024
    for record in session.records:
        for channel, count in enumerate(record.readings["mca"]):
            spectrum[channel] += count
    return session, spectrum


def centroid(spectrum, first, last):
    """Channel-weighted centroid in a known isolated peak ROI (inclusive)."""
    counts = sum(spectrum[first:last + 1])
    if counts == 0:
        raise AssertionError("Expected a populated peak ROI")
    return sum(c * spectrum[c] for c in range(first, last + 1)) / counts


class AlphaTransportTests(unittest.TestCase):
    def test_mass_thickness_and_published_csda_anchors(self):
        self.assertAlmostEqual(AluminumFoil(0.005).areal_density_g_cm2, 0.00135)
        # NIST Aluminum: R(5.5 MeV)=0.006678, R(5 MeV)=0.005825 g/cm².
        foil = AluminumFoil((0.006678 - 0.005825) / 2.70 * 10)
        self.assertAlmostEqual(transmitted_energy(5.5, foil), 5.0)
        stopping_foil = AluminumFoil(0.006678 / 2.70 * 10)
        self.assertAlmostEqual(transmitted_energy(5.5, stopping_foil), 0, delta=1e-12)

    def test_zero_foil_and_monotonic_loss_to_stopping(self):
        for incident in (5.155, 5.486, 5.805):
            self.assertAlmostEqual(transmitted_energy(incident, AluminumFoil(0)), incident)
            energies = [transmitted_energy(incident, AluminumFoil(t / 1000))
                        for t in range(41)]
            self.assertTrue(all(a >= b >= 0 for a, b in zip(energies, energies[1:])))
            self.assertEqual(energies[30], 0)

    def test_invalid_physical_inputs_fail_at_boundary(self):
        for energy in (-0.1, 6.1, math.inf, math.nan):
            with self.subTest(energy=energy), self.assertRaises(ValueError):
                transmitted_energy(energy, AluminumFoil(0))
        session = Session(EXPERIMENT)
        for thickness in (-1, 41, math.nan):
            with self.subTest(thickness=thickness), self.assertRaises(ValueError):
                session.set("foil_um", thickness)
        self.assertEqual(session.settings["foil_um"], 0)


class AlphaSpectrumTests(unittest.TestCase):
    def test_zero_foil_two_point_calibration_and_independent_third_peak(self):
        session, spectrum = acquire(0)
        self.assertEqual(sum(row.exposure_s for row in session.records), 60)
        self.assertTrue(all(len(row.readings["mca"]) == 1024 for row in session.records))
        # Fit the two outer peaks; Am-241 is an independent check of the fit.
        low = centroid(spectrum, 845, 874)
        middle = centroid(spectrum, 900, 929)
        high = centroid(spectrum, 952, 982)
        calibration = Calibration("alpha", "mca", 1024, low, 5.155, high, 5.805)
        self.assertAlmostEqual(calibration.energy(middle), 5.486, delta=0.003)
        self.assertAlmostEqual((5.805 - 5.155) / (high - low), 0.006, delta=0.00003)
        # Nominal detected rate is 25 counts/s per line; this is a 5σ bound.
        self.assertAlmostEqual(sum(spectrum), 75 * 60, delta=5 * math.sqrt(75 * 60))

    def test_observed_peak_shifts_at_two_foil_thicknesses(self):
        _, reference = acquire(0)
        low = centroid(reference, 845, 874)
        high = centroid(reference, 952, 982)
        calibration = Calibration("alpha", "mca", 1024, low, 5.155, high, 5.805)
        # Fixed expected values from the documented CSDA interpolation, not a
        # call to the model under test. ROIs enclose isolated acquired peaks.
        cases = (
            (5, ((703, 733), (764, 794), (824, 854)), (4.306741, 4.673632, 5.032984)),
            (15, ((349, 379), (434, 464), (514, 544)), (2.182392, 2.693925, 3.173441)),
        )
        for thickness, regions, expected in cases:
            _, spectrum = acquire(thickness)
            for roi, energy, incident in zip(regions, expected, (5.155, 5.486, 5.805)):
                with self.subTest(thickness_um=thickness, incident_mev=incident):
                    observed = calibration.energy(centroid(spectrum, *roi))
                    self.assertAlmostEqual(observed, energy, delta=0.008)
                    self.assertGreater(incident - observed, 0)

    def test_partial_and_complete_stopping_in_acquired_spectrum(self):
        _, partial = acquire(25)
        self.assertEqual(sum(partial[100:]), 0)
        self.assertAlmostEqual(centroid(partial, 55, 85) * 0.006, 0.422961, delta=0.003)
        self.assertAlmostEqual(sum(partial), 25 * 60, delta=5 * math.sqrt(25 * 60))
        session, stopped = acquire(30, seconds=2.25)
        self.assertEqual(stopped, [0] * 1024)
        self.assertEqual(sum(row.exposure_s for row in session.records), 2.25)

    def test_refresh_chunks_do_not_change_the_acquired_spectrum(self):
        reference, _ = acquire(5, seconds=1.25, seed=92)
        split = Session(EXPERIMENT, seed=92)
        split.set("foil_um", 5)
        split.start()
        for _ in range(25):
            split.advance(0.05)
        split.stop()
        self.assertEqual(split.records, reference.records)


if __name__ == "__main__":
    unittest.main()
