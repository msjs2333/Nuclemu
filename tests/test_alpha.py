"""Alpha spectroscopy acceptance checks using acquired channel histograms."""

import math
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe, discover
from nuclemu.core import Device, Experiment, Parameter, Session
from nuclemu.experiments.alpha import DETECTOR_OUTPUT, EXPERIMENT, configured_foil, transmitted_energy
from nuclemu.physics import AluminumFoil
from nuclemu.results import Calibration, MeasurementView


def acquire(thickness_um, seconds=60, seed=187):
    session = Session(EXPERIMENT, seed=seed)
    session.configure({"foil_spec_um": 1, "foil_count": thickness_um})
    session.set_output(DETECTOR_OUTPUT, True)
    session.start(seconds, device="mca")
    session.advance(seconds)
    session.stop(device="mca")
    session.set_output(DETECTOR_OUTPUT, False)
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
        for key, value in (("foil_count", -1), ("foil_count", 41), ("foil_count", 0.5),
                           ("foil_spec_um", 1.5), ("source_present", 2), ("foil_count", math.nan)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                session.set(key, value)
        self.assertEqual(session.settings["foil_count"], 0)

    def test_sheet_specification_count_and_areal_density(self):
        for specification, count, thickness_um in ((1, 0, 0), (1, 1, 1), (1, 5, 5), (2, 3, 6), (2, 40, 80)):
            session = Session(EXPERIMENT)
            session.configure({"foil_spec_um": specification, "foil_count": count})
            foil = configured_foil(session.settings)
            self.assertAlmostEqual(foil.thickness_mm, thickness_um / 1000)
            self.assertAlmostEqual(foil.areal_density_g_cm2, thickness_um * 2.70e-4)

    def test_legacy_live_settings_are_normalized_once_and_fail_atomically(self):
        session = Session(EXPERIMENT)
        session.configure({"foil_spec_um": 2, "foil_count": 3})
        session.set("foil_um", 5)
        self.assertEqual(dict(session.settings), {"source_present": 1, "foil_spec_um": 1.0, "foil_count": 5})
        session.configure({"foil_um": 0.0, "source_present": 0})
        self.assertEqual(session.settings["foil_count"], 0)
        session.set_output(DETECTOR_OUTPUT, True)
        session.start(device="mca")
        session.advance(0.25)
        before = dict(session.settings)
        for batch in ({"foil_um": 2.5, "source_present": 1}, {"foil_um": math.nan},
                      {"foil_um": True}, {"foil_um": -1}, {"foil_um": 41},
                      {"foil_um": 0, "foil_count": 0}, {"foil_um": 5, "foil_spec_um": 1}):
            with self.subTest(batch=batch), self.assertRaises(ValueError):
                session.configure(batch)
            self.assertEqual(dict(session.settings), before)
            self.assertEqual(session.records, [])
            self.assertEqual(session.time_s, 0.25)

    def test_different_sheet_stacks_of_equal_thickness_give_equal_spectra(self):
        _, expected = acquire(6, seconds=10)
        other = Session(EXPERIMENT, seed=187)
        other.configure({"foil_spec_um": 2, "foil_count": 3})
        other.set_output(DETECTOR_OUTPUT, True)
        other.start(10, device="mca")
        other.advance(10)
        counts = MeasurementView(other).product()["segments"][0]["readings"]["mca"]
        self.assertEqual(counts, expected)


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
        split.configure({"foil_spec_um": 1, "foil_count": 5})
        split.set_output(DETECTOR_OUTPUT, True)
        split.start()
        for _ in range(25):
            split.advance(0.05)
        split.stop()
        self.assertEqual(split.records, reference.records)


class AlphaEquipmentTests(unittest.TestCase):
    def test_apparatus_maps_independent_output_and_instrument(self):
        entry = describe(EXPERIMENT)
        parts = {part["id"]: part for part in entry["components"]}
        self.assertEqual(parts["source"]["parameters"], ("source_present",))
        self.assertEqual(parts["foil"]["parameters"], ("foil_spec_um", "foil_count"))
        self.assertEqual(parts["detector"]["output"], DETECTOR_OUTPUT)
        self.assertIsNone(parts["detector"]["device"])
        self.assertEqual(parts["mca"]["device"], "mca")
        self.assertEqual(entry["devices"][0]["input"], DETECTOR_OUTPUT)
        self.assertEqual(entry["outputs"][0]["channels"], 1024)
        self.assertNotIn("foil_um", {p["key"] for p in entry["parameters"]})

    def test_empty_source_is_independent_of_empty_foil(self):
        for source in (0, 1):
            for count in (0, 5):
                session = Session(EXPERIMENT, seed=187)
                session.configure({"source_present": source, "foil_count": count})
                session.set_output(DETECTOR_OUTPUT, True)
                session.start(2.25, device="mca")
                session.advance(2.25)
                product = MeasurementView(session).product()
                values = product["segments"][0]["readings"]["mca"]
                self.assertEqual(session.instrument("mca").exposure_s, 2.25)
                self.assertEqual(product["segments"][0]["settings"]["foil_count"], count)
                if source:
                    self.assertGreater(sum(values), 0)
                    region = (900, 929) if count == 0 else (764, 794)
                    center = centroid(values, *region)
                    self.assertAlmostEqual(center * 0.006, 5.486 if count == 0 else 4.673632, delta=0.008)
                else:
                    self.assertEqual(sum(values), 0)

    def test_closed_detector_and_closed_mca_have_different_exposures(self):
        closed = Session(EXPERIMENT)
        self.assertFalse(closed.output_enabled[DETECTOR_OUTPUT])
        closed.start(2.25, device="mca")
        closed.advance(2.25)
        self.assertEqual(closed.instrument("mca").exposure_s, 2.25)
        self.assertEqual(sum(MeasurementView(closed).product()["segments"][0]["readings"]["mca"]), 0)
        detector_only = Session(EXPERIMENT)
        detector_only.set_output(DETECTOR_OUTPUT, True)
        detector_only.advance(2.25)
        self.assertEqual(detector_only.time_s, 2.25)
        self.assertEqual(detector_only.instrument("mca").exposure_s, 0)
        self.assertEqual(detector_only.records, [])
        detector_only.set_output(DETECTOR_OUTPUT, False)
        detector_only.advance(10)
        self.assertEqual(detector_only.time_s, 2.25)

    def test_shared_alpha_output_delivers_identical_integer_spectra(self):
        definition = replace(EXPERIMENT, components=(), connections=(), devices=(
            EXPERIMENT.devices[0], Device("second", "spectrum", "第二台 MCA", 1024, input=DETECTOR_OUTPUT)))
        session = Session(definition, seed=187)
        session.set_output(DETECTOR_OUTPUT, True)
        session.start(5)
        session.advance(5)
        product = MeasurementView(session).product()
        spectra = {key: segment["readings"][key] for segment in product["segments"] for key in segment["readings"]}
        self.assertEqual(spectra["mca"], spectra["second"])

    def test_detector_off_in_middle_does_not_shorten_mca_exposure(self):
        session = Session(EXPERIMENT, seed=187)
        session.set_output(DETECTOR_OUTPUT, True)
        session.start(10, device="mca")
        session.advance(3)
        session.set_output(DETECTOR_OUTPUT, False)
        session.advance(4)
        session.set_output(DETECTOR_OUTPUT, True)
        session.advance(3)
        self.assertEqual(session.instrument("mca").exposure_s, 10)
        dark = [row for row in session.records if row.start_s >= 3 and row.end_s <= 7]
        self.assertEqual(sum(row.exposure_s for row in dark), 4)
        self.assertEqual(sum(sum(row.readings["mca"]) for row in dark), 0)
        bright = [row for row in session.records if row.end_s <= 3 or row.start_s >= 7]
        self.assertGreater(sum(sum(row.readings["mca"]) for row in bright), 0)

    def test_old_thickness_archive_and_fixed_calibration_stay_unmodified(self):
        from nuclemu.web_session import Application

        now = [0.0]
        values = tuple(4 if channel == 500 else 0 for channel in range(1024))
        old = Experiment("alpha", "α 旧厚度记录", "旧实验定义",
                         (Parameter("foil_um", "总厚度", "µm", 0, 0, 40),),
                         (Device("mca", "spectrum", "MCA", 1024),),
                         lambda *args: {"mca": values})
        with TemporaryDirectory() as directory:
            writer = Application({"alpha": old}, directory, lambda: now[0])
            state = writer.open({"experiment": "alpha", "seed": 187})
            def act(action, **fields):
                return writer.request("/api/action", {"session": state["id"], "action": action, **fields})
            act("configure", values={"foil_um": 2.5})
            act("start", duration=1)
            now[0] = 1
            state = writer.state()
            act("calibrate", points=[0, 0, 1000, 6], calibration_context=state["calibration_context"])
            act("save")
            document = writer.store.read(writer.lab.archive_id)
            document["definition"]["devices"][0].pop("input", None)
            writer.store.write("legacy-alpha-2-5", "archive", document)
            reader = Application(discover(), directory, lambda: now[0])
            restored = reader.open({"archive": "legacy-alpha-2-5"})
            self.assertEqual(restored["settings"], {"foil_um": 2.5})
            self.assertEqual(restored["product"], document["product"])
            self.assertNotIn("foil_count", restored["settings"])
            self.assertAlmostEqual(reader.lab.work.active_calibration().energy(500), 3.0)
            reader.request("/api/action", {"session": restored["id"], "action": "save"})
            copied = reader.store.read(reader.lab.archive_id)
            self.assertEqual(copied["settings"], {"foil_um": 2.5})
            self.assertEqual(copied["product"], document["product"])
        calibration = Calibration.from_document({"format": "nuclemu.calibration/1", "unit": "MeV",
            "experiment": "alpha", "device": "mca", "channels": 1024,
            "channel1": 0, "energy1": 0, "channel2": 1000, "energy2": 6})
        calibration.check(EXPERIMENT.id, "mca", 1024)
        self.assertTrue(calibration.applies_to({"foil_spec_um": 2, "foil_count": 3, "source_present": 1}))


if __name__ == "__main__":
    unittest.main()
