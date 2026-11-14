"""Loading partial measurements retains the receiver's applied next window."""

from dataclasses import replace
import unittest

from nuclemu.core import Device, Experiment, Session, SignalOutput


COURSE = Experiment('loaded-window', 'Loaded window', '', (),
    (Device('counter', 'counter', 'Counter', input='out'),),
    lambda settings, start, end, rng: {'out': (round(10 * (end-start)),)},
    outputs=(SignalOutput('out', 'Output'),))


class LoadedWindowSettingsTests(unittest.TestCase):
    def test_source_partial_finishes_before_receiver_pending_window(self):
        source = Session(COURSE)
        source.set_output('out', True)
        source.start(device='counter', window_s=4)
        source.advance(1)
        saved = source.snapshot('counter')
        receiver = Session(COURSE)
        receiver.start(device='counter', window_s=5)
        receiver.advance(1)
        receiver.configure_acquisition('counter', window_s=2)
        self.assertEqual((receiver.instrument('counter').window_s, receiver.instrument('counter').next_window_s), (5, 2))
        receiver.load_measurement('counter', saved, overwrite=True)
        self.assertEqual((receiver.instrument('counter').window_s, receiver.instrument('counter').next_window_s), (4, 2))
        receiver.start(device='counter')
        receiver.advance(5)
        self.assertEqual([(w.start_exposure_s, w.end_exposure_s, w.complete) for w in receiver.instrument_windows('counter')],
                         [(0, 4, True), (4, 6, True)])

    def test_legacy_prefix_is_readable_without_inventing_windows(self):
        source = Session(COURSE)
        source.set_output('out', True)
        source.start(device='counter')
        source.advance(1)
        saved = replace(source.snapshot('counter'), windows=())
        receiver = Session(COURSE)
        receiver.load_measurement('counter', saved)
        state = receiver.instrument('counter')
        self.assertEqual((state.window_prefix_exposure_s, state.window_prefix_counts), (1, (10,)))
        self.assertEqual(receiver.instrument_windows('counter'), ())
        receiver.start(device='counter')
        receiver.advance(1)
        state = receiver.instrument('counter')
        self.assertEqual((state.window_prefix_exposure_s, state.window_prefix_counts), (1, (10,)))
        self.assertEqual([(w.start_exposure_s, w.end_exposure_s, w.counts) for w in receiver.instrument_windows('counter')], [(1, 2, (0,))])


if __name__ == '__main__':
    unittest.main()
