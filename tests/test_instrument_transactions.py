"""Whole-instrument operations commit all members or preserve the original data."""

from dataclasses import replace
import unittest

from nuclemu.core import Device, Experiment, Session, SignalOutput


def course():
    return Experiment('transactions', 'Transactions', '', (),
        tuple(Device(d, 'counter', d, input=d) for d in ('a', 'b', 'c')),
        lambda settings, start, end, rng: {d: (round(rate * (end-start)),)
            for d, rate in (('a', 10), ('b', 20), ('c', 30))},
        outputs=tuple(SignalOutput(d, d) for d in ('a', 'b', 'c')))


def acquire():
    s = Session(course())
    for d in ('a', 'b', 'c'):
        s.set_output(d, True)
    s.start(10, device='a', window_s=1)
    s.start(10, device='b', window_s=5)
    s.start(device='c')
    s.advance(3)
    return s


class InstrumentTransactionTests(unittest.TestCase):
    def state(self, s):
        return tuple(s.instrument(d) for d in ('a', 'b', 'c')), s.snapshots, s.rounds, s.records, s._rng.getstate()

    def test_snapshot_preserves_partial_and_commits_only_after_one_group_writer(self):
        s = acquire()
        before = self.state(s)
        def fail(items):
            self.assertEqual([x.device for x in items], ['a', 'b'])
            self.assertEqual([x.id for x in items], [1, 2])
            self.assertEqual([len(x.windows) for x in items], [3, 1])
            self.assertFalse(items[1].windows[0].complete)
            raise OSError('whole cache failed')
        with self.assertRaisesRegex(OSError, 'whole cache failed'):
            s.snapshot_group(('a', 'b'), writer=fail)
        self.assertEqual(self.state(s), before)
        saved = s.snapshot_group(('a', 'b'))
        self.assertEqual([(x.id, x.counts, x.exposure_s) for x in saved], [(1, (30,), 3), (2, (60,), 3)])
        self.assertEqual([s.instrument(d).running for d in ('a', 'b', 'c')], [True] * 3)
        s.advance(1)
        self.assertEqual(saved[0].counts, (30,))

    def test_empty_side_has_no_snapshot_and_empty_instrument_is_rejected(self):
        s = Session(course())
        with self.assertRaisesRegex(ValueError, 'no readable'):
            s.snapshot_group(('a', 'b'))
        s.start(1, device='a')
        s.advance(1)
        items = s.snapshot_group(('a', 'b'))
        self.assertEqual([(x.device, x.counts, x.exposure_s) for x in items], [('a', (0,), 1)])

    def test_load_validates_all_members_before_replacing_and_missing_side_is_empty(self):
        source = acquire()
        saved = source.snapshot_group(('a', 'b'))
        target = acquire()
        before = self.state(target)
        with self.assertRaises(ValueError):
            target.load_measurements(('a', 'b'), saved)
        self.assertEqual(self.state(target), before)
        with self.assertRaises(ValueError):
            target.load_measurements(('a', 'b'), (saved[0], replace(saved[1], counts=(999,))), overwrite=True)
        self.assertEqual(self.state(target), before)
        target.load_measurements(('a', 'b'), saved, overwrite=True)
        self.assertEqual([(target.instrument(d).counts, target.instrument(d).exposure_s) for d in ('a', 'b')],
                         [((30,), 3), ((60,), 3)])
        self.assertTrue(target.instrument('c').running)
        target.start_group(('a', 'b'))
        target.advance(2)
        self.assertEqual([target.instrument(d).counts for d in ('a', 'b')], [(50,), (100,)])
        self.assertTrue(target.instrument_windows('b')[0].complete)
        target.load_measurements(('a', 'b'), (saved[0],), overwrite=True)
        self.assertEqual((target.instrument('b').counts, target.instrument('b').exposure_s), ((0,), 0))
        self.assertIsNone(target.instrument('b').acquisition)

    def test_group_clear_cancel_failure_and_save_restore_or_clear_both(self):
        for choice in ('cancel', 'failure', 'save', 'discard'):
            with self.subTest(choice=choice):
                s = acquire()
                requests = s.begin_clear_group(('a', 'b'))
                self.assertFalse(s.instrument('a').running)
                self.assertFalse(s.instrument('b').running)
                self.assertTrue(s.instrument('c').running)
                s.advance(2.5)
                tokens = {r.device: r.token for r in requests}
                def fail(items):
                    self.assertEqual([x.counts for x in items], [(30,), (60,)])
                    raise OSError('whole cache failed')
                if choice == 'failure':
                    with self.assertRaises(OSError):
                        s.finish_clear_group(('a', 'b'), tokens, 'save', writer=fail)
                else:
                    s.finish_clear_group(('a', 'b'), tokens, choice)
                s.advance(.5)
                self.assertEqual((s.instrument('c').counts, s.instrument('c').exposure_s), ((180,), 6))
                if choice in ('cancel', 'failure'):
                    self.assertEqual([(s.instrument(d).counts, s.instrument(d).exposure_s) for d in ('a', 'b')],
                                     [((35,), 3.5), ((70,), 3.5)])
                    self.assertEqual(s.snapshots, ())
                else:
                    self.assertEqual([s.instrument(d).exposure_s for d in ('a', 'b')], [0, 0])
                    self.assertEqual(len(s.snapshots), 2 if choice == 'save' else 0)
                with self.assertRaises(ValueError):
                    s.finish_clear_group(('a', 'b'), tokens, 'discard')


if __name__ == '__main__':
    unittest.main()
