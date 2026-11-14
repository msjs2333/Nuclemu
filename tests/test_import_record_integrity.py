"""Import preserves whole-instrument records and both live segment views."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Session
from nuclemu.experiments.beta import EXPERIMENT
from nuclemu.exchange import (capture_session, export_item, import_item, link_measurements,
    list_records, load_item, load_package, native_snapshot_id, package_bytes)
from nuclemu.web_import import apply_import, inspect_import
from nuclemu.web_portable import open_portable
from nuclemu.web_session import Application


DEVICES = ('counter', 'counter_b')


def saved_record():
    session = Session(EXPERIMENT, seed=187)
    session.set('source_present', 1)
    session.set_output('beta_detector', True)
    session.configure_acquisition('counter_b', window_s=5)
    session.start_group(DEVICES)
    session.advance(3)
    snapshots = session.snapshot_group(DEVICES)
    doc = capture_session(session)
    identity = link_measurements(doc, [native_snapshot_id(doc, s) for s in snapshots],
                                 'counter at 3 s', members=DEVICES)
    return doc, identity


class ImportRecordIntegrityTests(unittest.TestCase):
    def sources(self, folder):
        doc, identity = saved_record()
        for suffix, data in (('nuclemu', package_bytes(doc)),
                             ('json', export_item(doc, identity, 'json')),
                             ('csv', export_item(doc, identity, 'csv'))):
            path = Path(folder) / ('source.' + suffix)
            path.write_bytes(data)
            yield suffix, path.read_bytes(), identity

    def lab(self, folder):
        app = Application({'beta': EXPERIMENT}, folder, clock=lambda: 0)
        app.open({'experiment': 'beta', 'seed': 5})
        session = app.lab.work.session
        session.set_output('beta_detector', True)
        session.start_group(DEVICES)
        session.advance(1)
        return app.lab

    def test_selector_offers_one_record_for_each_file_format(self):
        with TemporaryDirectory() as folder:
            lab = self.lab(folder)
            for suffix, raw, identity in self.sources(folder):
                with self.subTest(format=suffix):
                    inspected = inspect_import(lab, raw)
                    rows = [r for r in inspected['items'] if r['kind'] == 'measurement']
                    self.assertEqual([r['id'] for r in rows], [identity])
                    self.assertEqual([m['device'] for m in rows[0]['measurements']], list(DEVICES))

    def test_primary_import_adds_all_member_segments_before_and_after_reopen(self):
        with TemporaryDirectory() as folder:
            for suffix, raw, identity in self.sources(folder):
                with self.subTest(format=suffix):
                    lab = self.lab(folder)
                    session = lab.work.session
                    before = tuple(session.instrument(d) for d in DEVICES), session._rng.getstate(), session.records
                    inspected = inspect_import(lab, raw)
                    result = apply_import(lab, inspected['token'], identity)
                    self.assertEqual((tuple(session.instrument(d) for d in DEVICES), session._rng.getstate(), session.records), before)
                    record = next(r for r in list_records(lab.exchange.document) if r['id'] == result['id'])
                    items = {i['id']: i for i in lab.exchange.document['items']}
                    original = {}
                    for member in record['group']['items']:
                        indices = lab.work.lab.view.item_indices[member]
                        expected = items[member]['document']['segments']
                        self.assertEqual([lab.work.product()['segments'][i] for i in indices], expected)
                        original[member] = indices
                    for fmt in ('json', 'csv'):
                        exported = Path(folder) / ('imported-' + suffix + '.' + fmt)
                        exported.write_bytes(export_item(lab.exchange.document, result['id'], fmt))
                        bundle = load_item(exported)
                        self.assertEqual([i['document']['snapshot']['device'] for i in bundle['items']], list(DEVICES))
                        self.assertEqual([len(i['document']['windows']) for i in bundle['items']], [3, 1])
                        self.assertFalse(bundle['items'][1]['document']['windows'][0]['complete'])
                    package = Path(folder) / ('imported-' + suffix + '.nuclemu')
                    package.write_bytes(lab.portable_download()[2])
                    reopened = open_portable(package.read_bytes(), {'beta': EXPERIMENT}, lab.store, lambda: 0)
                    for member, indices in original.items():
                        self.assertEqual(reopened.work.lab.view.item_indices[member], indices)
                        self.assertEqual([reopened.work.product()['segments'][i] for i in indices], items[member]['document']['segments'])

    def test_companion_cannot_be_imported_as_a_legacy_single_but_true_single_can(self):
        with TemporaryDirectory() as folder:
            for suffix, raw, identity in self.sources(folder):
                with self.subTest(format=suffix):
                    source = load_package(raw) if suffix == 'nuclemu' else load_item(raw)
                    target = capture_session(Session(EXPERIMENT))
                    before = deepcopy(target)
                    companion = source['items'][1]['id']
                    with self.assertRaisesRegex(ValueError, 'whole|primary|整机'):
                        import_item(target, source, companion)
                    self.assertEqual(target, before)
                    legacy = deepcopy(source)
                    legacy['items'] = [legacy['items'][1]]
                    imported = import_item(target, legacy, companion)
                    self.assertEqual(target['items'][0]['id'], imported)
                    self.assertNotIn('group', target['items'][0])
                    self.assertEqual(target['items'][0]['document']['snapshot']['device'], 'counter_b')


if __name__ == '__main__':
    unittest.main()
