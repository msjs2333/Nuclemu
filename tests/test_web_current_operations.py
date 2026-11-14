"""Current-instrument caching and clear decisions preserve the other live gate."""

from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.web_session import Application


class CurrentWebOperationsTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.app = Application(discover(['examples/courses']), self.folder.name, lambda: self.now)
        self.app.open({'experiment': 'split-signal', 'seed': 187})

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def both(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a', duration=10)
        self.call('device', device='b')
        self.call('start', device='b', duration=10)
        self.call('device', device='a')

    def test_save_copies_readable_exposure_and_keeps_sampling_during_writer(self):
        self.both()
        self.now = 3
        self.app.lab.cache_writer = lambda item: setattr(self, 'now', 5)
        state = self.call('snapshot', device='a')
        session = self.app.lab.work.session
        self.assertTrue(state['running'])
        self.assertEqual(state['exposure_s'], 5)
        self.assertEqual(session.instrument('b').exposure_s, 5)
        first = session.snapshots[0]
        self.assertEqual(first.exposure_s, 3)
        self.app.lab.cache_writer = None
        self.call('snapshot', device='a')
        self.assertEqual([s.exposure_s for s in session.snapshots], [3, 5])
        self.assertEqual(first.counts, session.snapshots[0].counts)
        self.assertEqual(first.acquisition, session.snapshots[1].acquisition)

    def test_clear_choices_and_failed_cache_hold_only_the_target(self):
        for choice in ('save', 'discard', 'cancel', 'failure'):
            with self.subTest(choice=choice):
                self.setUp()
                self.both()
                self.now = 3
                request = self.call('begin_clear', device='a')['clear_confirmation']
                session = self.app.lab.work.session
                self.now = 5
                state = self.app.state()
                self.assertEqual(state['exposure_s'], 3)
                self.assertEqual(session.instrument('b').exposure_s, 5)
                def writer(item):
                    self.assertEqual(item.exposure_s, 3)
                    self.now = 7
                    if choice == 'failure':
                        raise OSError('cache write failed')
                self.app.lab.cache_writer = writer
                # Another page can select B while the held decision still names A.
                self.call('device', device='b')
                fields = dict(device='a', token=request['token'], choice='save' if choice == 'failure' else choice)
                if choice == 'failure':
                    with self.assertRaisesRegex(OSError, 'cache write failed'):
                        self.call('finish_clear', **fields)
                else:
                    self.call('finish_clear', **fields)
                a, b = session.instrument('a'), session.instrument('b')
                self.assertTrue(b.running)
                self.assertEqual(b.exposure_s, 7 if choice in ('save', 'failure') else 5)
                if choice in ('cancel', 'failure'):
                    self.assertTrue(a.running)
                    self.assertEqual((a.exposure_s, a.remaining_s), (3, 7))
                    self.assertEqual(session.snapshots, ())
                else:
                    self.assertFalse(a.running)
                    self.assertIsNone(a.acquisition)
                    self.assertEqual(a.exposure_s, 0)
                    self.assertEqual(len(session.snapshots), 1 if choice == 'save' else 0)

    def test_applying_larger_target_does_not_start_until_continue(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a', duration=1)
        self.call('device', device='b')
        self.call('start', device='b')
        self.call('device', device='a')
        self.now = 1
        first = self.call('snapshot', device='a')
        self.call('instrument_config', device='a', duration_s=3, count_limit=None)
        self.now = 2
        state = self.app.state()
        self.assertFalse(state['running'])
        self.assertEqual(state['exposure_s'], 1)
        self.assertEqual(self.app.lab.work.session.instrument('b').exposure_s, 2)
        self.call('start', device='a')
        self.now = 4
        state = self.app.state()
        self.assertFalse(state['running'])
        self.assertEqual(state['exposure_s'], 3)
        self.assertEqual(state['instrument']['acquisition'], first['instrument']['acquisition'])
        self.assertEqual(self.app.lab.work.session.snapshots[0].exposure_s, 1)

    def test_live_cache_poll_and_exit_never_write_long_term_archives(self):
        with patch.object(self.app.store, 'write', side_effect=AssertionError('Live course must not archive raw readings')), \
                patch.object(self.app.store, 'remove', side_effect=AssertionError('Live close must not touch old archives')):
            self.both()
            self.now = 3
            self.call('snapshot', device='a')
            self.now = 5
            current = self.app.state()
            for _ in range(3):
                self.assertEqual(self.app.state(session=current['id'])['id'], current['id'])
            token = self.call('freeze')['confirmation_id']
            package = self.app.lab.portable_download()[2]
            from nuclemu.exchange import load_package
            doc = load_package(package)
            self.assertEqual(len(doc['items']), 1)
            self.assertEqual(doc['items'][0]['document']['snapshot']['exposure_s'], 3)
            self.call('discard', confirmation_id=token)
        self.assertIsNone(self.app.lab)
        self.assertEqual(self.app.catalog()['archives'], [])
        self.assertEqual(self.app.catalog()['drafts'], [])


if __name__ == '__main__':
    unittest.main()
