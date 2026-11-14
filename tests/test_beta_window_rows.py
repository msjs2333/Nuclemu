"""Course window/condition contract checked through public acquisition APIs."""
from copy import deepcopy
import unittest

from examples.beta_window_rows import acquire, pause_resume, rows
from nuclemu.core import Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT


class BetaWindowRowsTests(unittest.TestCase):
    def test_five_short_and_one_long_retain_the_midwindow_foil_change(self):
        session = acquire()
        result = rows(session)
        short, long = result['counter'], result['counter_b']
        self.assertEqual(len(short), 5)
        self.assertEqual(len(long), 1)
        self.assertEqual([r['exposure_s'] for r in short], [1] * 5)
        self.assertEqual([r['counts'] for r in short], [[11693], [11727], [6546], [1490], [1434]])
        self.assertEqual((long[0]['exposure_s'], long[0]['counts']), (5, [32879]))
        self.assertTrue(all(r['complete'] for r in short + long))
        cross = short[2]['parts']
        self.assertEqual([(p['start_s'], p['end_s'], p['settings']['foil_count']) for p in cross],
                         [(2, 2.5, 0), (2.5, 3, 4)])
        self.assertEqual([p['readings']['counter'] for p in cross], [[5808], [738]])
        self.assertEqual(session.snapshots[0].windows, session.instrument_windows('counter'))
        # Display polling and flow calls preserve this exact operation line.
        self.assertEqual(rows(acquire(chunks=.1)), result)

    def test_retime_finishes_current_window_then_changes_only_a(self):
        result = rows(acquire(retime=True))
        self.assertEqual([r['exposure_s'] for r in result['counter']], [1, 1, 1, 2])
        self.assertEqual([r['counts'] for r in result['counter']], [[11693], [11727], [6546], [2924]])
        self.assertEqual([r['exposure_s'] for r in result['counter_b']], [5])
        self.assertEqual(result['counter_b'], rows(acquire())['counter_b'])

    def test_zero_completed_window_is_distinct_from_not_yet_measured(self):
        s = Session(EXPERIMENT, seed=42)
        self.assertEqual(s.instrument_windows('counter'), ())
        # Closed detector, open gate: an exposed zero is a real window.
        s.start(1, device='counter', window_s=1)
        s.advance(1)
        window, = s.instrument_windows('counter')
        self.assertEqual(window.counts, (0,))
        self.assertEqual(window.end_exposure_s - window.start_exposure_s, 1)
        self.assertTrue(window.complete)

    def test_pause_a_leaves_b_and_the_old_snapshot_unchanged(self):
        # Low-level gate independence remains supported; the student UI uses
        # one group operation for this counter's pair of windows.
        s = Session(EXPERIMENT, seed=42)
        s.set('source_present', 1)
        s.set_output(DETECTOR_OUTPUT, True)
        s.start(device='counter', window_s=1)
        s.start(device='counter_b', window_s=5)
        s.advance(3)
        saved = s.snapshot('counter')
        short = deepcopy(rows(s)['counter'])
        s.stop(device='counter')
        s.advance(2)
        self.assertEqual(rows(s)['counter'], short)
        self.assertEqual(len(rows(s)['counter_b']), 1)
        self.assertTrue(rows(s)['counter_b'][0]['complete'])
        self.assertEqual(s.snapshots[0], saved)
        self.assertEqual(s.instrument('counter').exposure_s, 3)
        self.assertEqual(s.instrument('counter_b').exposure_s, 5)

    def test_counter_wide_pause_resume_excludes_waiting_from_both_exposures(self):
        s = pause_resume()
        self.assertEqual(s.time_s, 12)
        self.assertEqual([s.instrument(d).exposure_s for d in ('counter', 'counter_b')], [5, 5])
        self.assertTrue(all(not s.instrument(d).running for d in ('counter', 'counter_b')))
        self.assertEqual([s.instrument(d).acquisition for d in ('counter', 'counter_b')], [1, 1])
        self.assertEqual([snapshot.exposure_s for snapshot in s.snapshots], [3, 3])
        self.assertEqual([len(v) for v in rows(s).values()], [5, 1])
        self.assertEqual([(p.start_s, p.end_s) for p in s.instrument_windows('counter_b')[0].parts],
                         [(0, 1), (1, 2), (2, 3), (10, 11), (11, 12)])


if __name__ == '__main__':
    unittest.main()
