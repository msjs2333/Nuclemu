"""Measured course examples preserve zero counts, provenance and raw readings."""

import unittest

from examples.beta_background import overlapping_snapshots, zero_sample


class BetaBackgroundExamplesTests(unittest.TestCase):
    def test_actual_zero_sample_and_negative_rate_keep_measured_exposure(self):
        result = zero_sample()
        windows = result['saved_windows']
        self.assertEqual([s['counts'] for s in windows], [[1], [0]])
        self.assertEqual([s['exposure_s'] for s in windows], [.001, .001])
        self.assertNotEqual(windows[0]['acquisition'], windows[1]['acquisition'])
        self.assertEqual(result['uncorrected'], {'counts': 0, 'exposure_s': .001, 'rate': 0})
        self.assertEqual(result['corrected']['net_rate'], -1000)
        self.assertEqual(result['corrected']['uncertainty'], 1000)
        rows = result['product']['segments']
        self.assertEqual([r['settings']['source_present'] for r in rows], [0, 1])
        self.assertEqual([(r['start_s'], r['end_s']) for r in rows], [(0, .001), (.001, .002)])

    def test_cumulative_snapshots_keep_their_own_cutoff_and_shared_round(self):
        result = overlapping_snapshots()
        first, second = result['saved_windows']
        self.assertEqual((first['exposure_s'], second['exposure_s']), (3, 5))
        self.assertEqual(first['acquisition'], second['acquisition'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertLessEqual(first['counts'][0], second['counts'][0])
        self.assertEqual(result['shared_exposure_s'], 3)
        self.assertFalse(result['independent_poisson_subtraction'])


if __name__ == '__main__':
    unittest.main()
