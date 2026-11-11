import unittest

from nuclemu.core import Session
from nuclemu.experiments.beta import EXPERIMENT
from nuclemu.results import Calibration, MeasurementView, collect, roi_centroid


class MeasurementViewTests(unittest.TestCase):
    def test_view_uses_actual_session_seed(self):
        session = Session(EXPERIMENT, seed=42)
        self.assertEqual(MeasurementView(session).product()["seed"], 42)
        with self.assertRaisesRegex(ValueError, "seed"):
            MeasurementView(session, 1234)

    def test_calibration_needs_a_device_id(self):
        with self.assertRaisesRegex(ValueError, "device id"):
            Calibration("alpha", None, 1024, 100, 1, 200, 2)

    def test_adjacent_repeats_remain_distinct_in_live_and_batch_results(self):
        session = Session(EXPERIMENT, seed=42)
        view = MeasurementView(session, seed=42)
        session.start(1.25)
        session.advance(1)
        self.assertEqual(view.product()["segments"][0]["end_s"], 1)
        session.advance(0.25)
        session.start(2)
        session.advance(1)
        session.set("foil_count", 4)
        session.advance(1)
        product = view.product()
        self.assertEqual(product, collect(EXPERIMENT, session.records, 42))
        self.assertEqual([s["acquisition"] for s in product["segments"]], [1, 2, 2])
        self.assertEqual([s["end_s"] for s in product["segments"]], [1.25, 2.25, 3.25])
        self.assertIs(product, view.product())

    def test_roi_uses_both_endpoints_and_handles_zero_counts(self):
        self.assertEqual(roi_centroid([0, 1, 3, 12], 1, 2), 1.75)
        self.assertEqual(roi_centroid([0, 3], 1, 1), 1)
        self.assertIsNone(roi_centroid([0, 0], 0, 1))
        with self.assertRaises(ValueError):
            roi_centroid([1, 2], -1, 1)
