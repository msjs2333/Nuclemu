"""The save key captures data; a delayed name publishes only that observation."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Session
from nuclemu.catalog import discover
from nuclemu.exchange import load_package, load_item, export_item
from nuclemu.web_session import Application
from test_web_instrument_records import course


class SnapshotNamingTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.now = 0
        self.app = Application({'boxes': course()}, folder.name, lambda: self.now)
        self.app.open({'experiment': 'boxes'})
        self.call('output', output='detector', enabled=True)
        self.call('window_config', component='pair', device='b', window_s=5)
        self.call('start_group', component='pair')
        self.now = 3
        self.app.state()

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def begin(self):
        lab = self.app.lab
        return self.call('begin_snapshot_group', component='pair', device='a',
            acquisitions={d: lab.work.session.instrument(d).acquisition for d in ('a', 'b')})['pending_snapshot']

    def test_delayed_name_saves_three_seconds_while_live_reaches_five_and_files_reopen(self):
        lab = self.app.lab
        before = (lab.work.session.records[:], lab.work.session.instrument('b'), lab.work.session._rng.getstate())
        pending = self.begin()
        self.assertEqual(pending['exposures'], {'a': 3, 'b': 3})
        self.assertEqual(lab.work.session.snapshots, ())
        self.assertEqual((lab.work.session.records, lab.work.session.instrument('b'), lab.work.session._rng.getstate()), before)
        self.now = 5
        live = self.app.state()['instruments']
        saved = self.call('commit_snapshot_group', token=pending['token'], title='at 3 seconds')
        self.assertIsNone(saved['pending_snapshot'])
        self.assertEqual([s.exposure_s for s in lab.work.session.snapshots], [3, 3])
        self.assertEqual(saved['instruments'], live)
        self.assertEqual([s.counts for s in lab.work.session.snapshots], [(30,), (30,)])
        self.assertFalse(lab.work.session.snapshots[1].windows[0].complete)
        self.assertTrue(lab.work.session.instrument_windows('b')[0].complete)
        record = saved['records'][0]
        self.assertEqual(record['title'], 'at 3 seconds')
        for fmt in ('json', 'csv'):
            raw = export_item(lab.exchange.document, record['id'], fmt)
            path = self.folder / ('captured.' + fmt)
            path.write_bytes(raw)
            doc = load_item(path)
            self.assertEqual([i['document']['snapshot']['exposure_s'] for i in doc['items']], [3, 3])
        path = self.folder / 'captured.nuclemu'
        path.write_bytes(lab.portable_download()[2])
        doc = load_package(path)
        self.assertEqual([i['document']['snapshot']['exposure_s'] for i in doc['items']], [3, 3])
        self.assertEqual([r['exposure_s'] for r in doc['rounds']], [5, 5])

    def test_cancel_has_no_record_and_completed_token_cannot_be_reused(self):
        pending = self.begin()
        self.now = 5
        state = self.call('cancel_snapshot_group', token=pending['token'])
        self.assertIsNone(state['pending_snapshot'])
        self.assertEqual(state['records'], [])
        self.assertEqual(self.app.lab.work.session.snapshots, ())
        self.assertEqual(state['instruments']['b']['exposure_s'], 5)
        with self.assertRaisesRegex(ValueError, '已过期'):
            self.call('commit_snapshot_group', token=pending['token'], title='cancelled')

    def test_second_page_replaces_pending_and_stale_actions_do_not_consume_new_token_or_clock(self):
        old = self.begin()
        self.now = 4
        new = self.begin()
        self.now = 6
        for action in ('commit_snapshot_group', 'cancel_snapshot_group'):
            with self.assertRaisesRegex(ValueError, '已过期'):
                self.call(action, token=old['token'], title='stale')
            self.assertEqual(self.app.lab.work.session.time_s, 4)
            self.assertEqual(self.app.lab._pending_snapshot['token'], new['token'])
        self.call('commit_snapshot_group', token=new['token'], title='new page')
        self.assertEqual([s.exposure_s for s in self.app.lab.work.session.snapshots], [4, 4])

    def test_bad_name_and_second_member_write_failure_preserve_capture_for_retry(self):
        pending = self.begin()
        lab = self.app.lab
        self.now = 5
        with self.assertRaises(ValueError):
            self.call('commit_snapshot_group', token=pending['token'], title=' ')
        self.assertEqual(lab.work.session.time_s, 3)
        def fail(snapshot):
            if snapshot.device == 'b':
                raise OSError('second writer failed')
        lab.cache_writer = fail
        with self.assertRaisesRegex(OSError, 'second writer failed'):
            self.call('commit_snapshot_group', token=pending['token'], title='retry me')
        self.assertEqual(lab.work.session.snapshots, ())
        self.assertIsNone(lab.exchange.document)
        self.assertEqual(lab._pending_snapshot['token'], pending['token'])
        self.assertEqual(lab.work.session.instrument('a').exposure_s, 5)
        lab.cache_writer = None
        state = self.call('commit_snapshot_group', token=pending['token'], title='retry me')
        self.assertEqual([s.id for s in lab.work.session.snapshots], [1, 2])
        self.assertEqual([s.exposure_s for s in lab.work.session.snapshots], [3, 3])
        self.assertEqual(len(state['records']), 1)
        with self.assertRaisesRegex(ValueError, '已过期'):
            self.call('commit_snapshot_group', token=pending['token'], title='duplicate')

    def test_other_page_clear_and_new_round_keep_captured_old_round(self):
        pending = self.begin()
        clear = self.call('begin_clear_group', component='pair', device='a')['clear_confirmation']
        self.call('finish_clear_group', component='pair', token=clear['token'], choice='discard')
        self.call('start_group', component='pair')
        self.now = 4
        state = self.call('commit_snapshot_group', token=pending['token'], title='old round observation')
        self.assertEqual([s.acquisition for s in self.app.lab.work.session.snapshots], [1, 1])
        self.assertEqual([s.exposure_s for s in self.app.lab.work.session.snapshots], [3, 3])
        self.assertEqual(state['instruments']['a']['acquisition'], 2)
        self.assertEqual(state['instruments']['a']['exposure_s'], 1)

    def test_selection_change_and_another_cached_record_do_not_change_frozen_scope_or_ids(self):
        pending = self.begin()
        self.call('snapshot_group', component='pair', device='a', title='other save', acquisitions={'a': 1, 'b': 1})
        self.call('device', device='c')
        self.now = 5
        self.call('commit_snapshot_group', token=pending['token'], title='first key')
        self.assertEqual([s.id for s in self.app.lab.work.session.snapshots], [1, 2, 3, 4])
        self.assertEqual([s.device for s in self.app.lab.work.session.snapshots], ['a', 'b', 'a', 'b'])
        self.assertEqual([s.exposure_s for s in self.app.lab.work.session.snapshots], [3, 3, 3, 3])

    def test_stale_begin_does_not_advance_or_replace_pending(self):
        pending = self.begin()
        self.now = 5
        with self.assertRaisesRegex(ValueError, '轮次已改变'):
            self.call('begin_snapshot_group', component='pair', device='a', acquisitions={'a': 2, 'b': 1})
        self.assertEqual(self.app.lab.work.session.time_s, 3)
        self.assertEqual(self.app.lab._pending_snapshot['token'], pending['token'])

    def test_empty_member_does_not_acquire_later_data_during_naming(self):
        clear = self.call('begin_clear_group', component='pair', device='a')['clear_confirmation']
        self.call('finish_clear_group', component='pair', token=clear['token'], choice='discard')
        self.call('start', device='a')
        self.now = 4
        pending = self.begin()
        self.assertEqual(pending['exposures'], {'a': 1, 'b': 0})
        self.call('device', device='b')
        self.call('start', device='b')
        self.now = 6
        self.call('commit_snapshot_group', token=pending['token'], title='only readable A')
        self.assertEqual([(s.device, s.exposure_s) for s in self.app.lab.work.session.snapshots], [('a', 1)])
        self.assertEqual(self.app.lab.work.session.instrument('b').exposure_s, 2)

    def test_replaced_session_does_not_accept_the_old_page_token(self):
        old_session = self.app.lab.id
        pending = self.begin()
        confirmation = self.call('freeze')['confirmation_id']
        self.call('discard', confirmation_id=confirmation)
        self.app.open({'experiment': 'boxes'})
        with self.assertRaises(ValueError):
            self.app.request('/api/action', dict(session=old_session, action='commit_snapshot_group', token=pending['token'], title='old session'))
        with self.assertRaisesRegex(ValueError, '已过期'):
            self.call('commit_snapshot_group', token=pending['token'], title='old token')
        self.assertEqual(self.app.lab.work.session.snapshots, ())


class CapturedPublicationTests(unittest.TestCase):
    def test_publication_validates_all_members_without_sampling_and_failed_writer_allocates_no_ids(self):
        s = Session(course())
        s.set_output('detector', True)
        s.start_group(('a', 'b'))
        s.advance(3)
        frozen = s.snapshot_group(('a', 'b'), cache=False)
        s.advance(2)
        before = (s.records[:], s.instrument('a'), s._rng.getstate(), s.snapshots)
        with self.assertRaises(ValueError):
            s.cache_snapshots(('a', 'b'), (frozen[0], replace(frozen[1], counts=(999,))))
        def fail(items):
            raise OSError('atomic failure')
        with self.assertRaises(OSError):
            s.cache_snapshots(('a', 'b'), frozen, writer=fail)
        self.assertEqual((s.records, s.instrument('a'), s._rng.getstate(), s.snapshots), before)
        saved = s.cache_snapshots(('a', 'b'), frozen)
        self.assertEqual([x.id for x in saved], [1, 2])
        self.assertEqual([x.exposure_s for x in saved], [3, 3])


class SpectrumNamingTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 0
        self.app = Application(discover(), folder.name, lambda: self.now)
        self.app.open({'experiment': 'alpha', 'seed': 187})
        self.call('configure', values={'source_present': 1})
        self.call('output', output='alpha_detector', enabled=True)
        self.call('start', device='mca')
        self.now = 3
        self.app.state()

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def calibration(self, energy):
        state = self.app.state()
        self.call('calibrate', device='mca', calibration_context=state['calibration_context'], points=[0, 0, 1000, energy])
        state = self.app.state()
        return self.call('cache_calibration', device='mca', calibration_context=state['calibration_context'], title=f'cal {energy}')

    def test_spectrum_and_calibration_are_captured_before_other_page_changes_them(self):
        state = self.calibration(6)
        cal_id = state['cached_calibrations'][0]['id']
        pending = self.call('begin_snapshot_group', component='mca', device='mca', acquisitions={'mca': 1})['pending_snapshot']
        frozen = self.app.lab._pending_snapshot['snapshots'][0]
        self.now = 5
        self.calibration(3)
        self.call('commit_snapshot_group', token=pending['token'], title='three second spectrum')
        saved = self.app.lab.work.session.snapshots[0]
        self.assertEqual(saved.counts, frozen.counts)
        self.assertEqual(saved.exposure_s, 3)
        self.assertEqual(self.app.lab.work.session.instrument('mca').exposure_s, 5)
        item = next(i for i in self.app.lab.exchange.document['items'] if i['kind'] == 'measurement')
        self.assertEqual(item['calibration_id'], cal_id)
        self.assertEqual(self.app.state()['calibration']['energy2'], 3)

    def test_later_calibration_does_not_silently_change_uncalibrated_capture(self):
        pending = self.call('begin_snapshot_group', component='mca', device='mca', acquisitions={'mca': 1})['pending_snapshot']
        self.now = 5
        self.calibration(6)
        self.call('commit_snapshot_group', token=pending['token'], title='uncalibrated key')
        item = next(i for i in self.app.lab.exchange.document['items'] if i['kind'] == 'measurement')
        self.assertNotIn('calibration_id', item)


if __name__ == '__main__':
    unittest.main()
