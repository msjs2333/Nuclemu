"""Named whole-instrument records survive real files and failed transactions."""

from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from nuclemu.core import Component, Device, Experiment, SignalOutput
from nuclemu.exchange import load_package, load_item, export_item, list_records
from nuclemu.web_session import Application


def course():
    return Experiment('boxes', 'Boxes', '', (),
        tuple(Device(d, 'counter', d, input='detector') for d in ('a', 'b', 'c')),
        lambda settings, start, end, rng: {'detector': (round(10 * (end-start)),)},
        outputs=(SignalOutput('detector', 'Detector'),),
        components=(Component('pair', 'instrument', 'Pair', device='a', devices=('a', 'b')),
                    Component('solo', 'instrument', 'Solo', device='c')))


class WebInstrumentRecordTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
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

    def save(self, title='same name'):
        return self.call('snapshot_group', component='pair', device='a', title=title,
            acquisitions={d: self.app.lab.work.session.instrument(d).acquisition for d in ('a', 'b')})

    def inspect(self, raw=None):
        from base64 import b64encode
        return self.app.request('/api/inspect_measurement', dict(session=self.app.lab.id, component='pair',
            **({'file': b64encode(raw).decode()} if raw else {})))

    def test_group_name_stable_identity_partial_and_real_file_roundtrips(self):
        first = self.save()['records'][0]
        self.assertEqual(len(first['measurements']), 2)
        doc = self.app.lab.exchange.document
        b = next(i for i in doc['items'] if i['document']['snapshot']['device'] == 'b')
        self.assertFalse(b['document']['windows'][0]['complete'])
        self.assertEqual(b['document']['snapshot']['exposure_s'], 3)
        second = self.save()['records'][1]
        self.assertNotEqual(first['id'], second['id'])
        renamed = self.call('rename_record', item_id=first['id'], title=' renamed ')
        self.assertEqual(renamed['records'][0]['id'], first['id'])
        self.assertEqual(renamed['records'][0]['title'], 'renamed')
        for fmt in ('json', 'csv'):
            raw = export_item(self.app.lab.exchange.document, first['id'], fmt)
            with TemporaryDirectory() as folder:
                path = Path(folder) / ('measurement.' + fmt)
                path.write_bytes(raw)
                package = load_item(path)
                raw = path.read_bytes()
            self.assertEqual(len(package['items']), 2)
            choice = self.inspect(raw)
            self.assertEqual(len(choice['items']), 1)
            self.call('load_measurement', token=choice['token'], item_id=choice['items'][0]['id'], overwrite=True)
            self.assertEqual([self.app.lab.work.session.instrument(d).exposure_s for d in ('a', 'b')], [3, 3])
        reopened = load_package(self.app.lab.portable_download()[2])
        self.assertEqual([r['title'] for r in list_records(reopened)], ['renamed', 'same name'])

    def test_blank_stale_and_second_writer_failure_do_not_cache_half_a_record(self):
        lab = self.app.lab
        for title in ('', '   '):
            with self.assertRaises(ValueError):
                self.save(title)
        self.assertEqual(lab.work.session.snapshots, ())
        self.save()
        before = deepcopy(lab.exchange.document)
        snapshots = lab.work.session.snapshots
        def fail(snapshot):
            if snapshot.device == 'b':
                raise OSError('second member failed')
        lab.cache_writer = fail
        with self.assertRaises(OSError):
            self.save()
        self.assertEqual(lab.exchange.document, before)
        self.assertEqual(lab.work.session.snapshots, snapshots)
        self.now = 4
        with self.assertRaises(ValueError):
            self.call('snapshot_group', component='pair', device='a', title='stale', acquisitions={'a': 999, 'b': 1})
        self.assertEqual(lab.work.session.time_s, 3)

    def test_clear_one_confirmation_restores_both_on_failure_or_cancel(self):
        lab = self.app.lab
        confirmation = self.call('begin_clear_group', component='pair', device='a')['clear_confirmation']
        self.assertEqual(confirmation['exposures'], {'a': 3, 'b': 3})
        self.now = 5
        def fail(snapshot):
            if snapshot.device == 'b':
                raise OSError('failed')
        lab.cache_writer = fail
        with self.assertRaises(OSError):
            self.call('finish_clear_group', component='pair', token=confirmation['token'], choice='save', title='failed')
        self.assertIsNone(self.app.state()['clear_confirmation'])
        self.assertEqual(lab.work.session.snapshots, ())
        self.assertTrue(all(lab.work.session.instrument(d).running for d in ('a', 'b')))
        lab.cache_writer = None
        self.now = 6
        confirmation = self.call('begin_clear_group', component='pair', device='a')['clear_confirmation']
        self.call('finish_clear_group', component='pair', token=confirmation['token'], choice='save', title='clear')
        self.assertEqual(len(lab.work.session.snapshots), 2)
        self.assertEqual([lab.work.session.instrument(d).exposure_s for d in ('a', 'b')], [0, 0])

    def test_zero_side_load_clears_missing_member_and_old_singles_are_not_paired(self):
        lab = self.app.lab
        self.save()
        doc = deepcopy(lab.exchange.document)
        # A historical single item remains readable through the device route.
        first = doc['items'][0]
        first.pop('group')
        doc['items'] = [first]
        raw = export_item(doc, first['id'])
        historical = self.inspect(raw)
        self.assertTrue(historical['items'][0]['historical_single'])
        before_b = lab.work.session.instrument('b')
        self.call('load_measurement', token=historical['token'], item_id=first['id'], overwrite=True)
        self.assertEqual(lab.work.session.instrument('b'), before_b)
        confirmation = self.call('begin_clear_group', component='pair', device='a')['clear_confirmation']
        self.call('finish_clear_group', component='pair', token=confirmation['token'], choice='discard')
        self.call('start', device='a', duration=1)
        self.now += 1
        state = self.save('a only')
        only = state['records'][-1]
        self.assertEqual(len(only['measurements']), 1)
        self.call('instrument_group_config', component='pair', duration_s=None)
        self.call('start_group', component='pair')
        self.now += 1
        choice = self.inspect()
        self.call('load_measurement', token=choice['token'], item_id=only['id'], overwrite=True)
        self.assertEqual(lab.work.session.instrument('b').exposure_s, 0)
        self.assertIsNone(lab.work.session.instrument('b').acquisition)

    def test_single_instrument_keeps_single_record_and_inferred_binding(self):
        from dataclasses import replace
        definition = replace(course(), devices=(course().devices[0],), components=())
        self.app = Application({'boxes': definition}, self.app.store.directory, lambda: self.now)
        state = self.app.open({'experiment': 'boxes'})
        part = next(p for p in state['definition']['components'] if p['kind'] == 'instrument')
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a')
        self.now += 2
        state = self.call('snapshot_group', component=part['id'], device='a', title='one instrument', acquisitions={'a': 1})
        self.assertEqual(len(state['records']), 1)
        self.assertNotIn('group', self.app.lab.exchange.document['items'][0])
        self.assertEqual(state['records'][0]['title'], 'one instrument')


if __name__ == '__main__':
    unittest.main()
