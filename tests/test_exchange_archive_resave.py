"""Converted archive references retain identity beside imported copies."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe
from nuclemu.core import Device, Experiment
from nuclemu.exchange import (archive_package, convert_archive, import_item,
                              load_package, package_bytes, save_package)
from nuclemu.web_portable import open_portable
from nuclemu.web_store import ArchiveStore


class ArchiveResaveIdentityTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.store = ArchiveStore(self.folder / 'store')
        def unavailable(*args):
            raise AssertionError('Reopening archived readings must not run a model')
        self.definition = Experiment('old', 'Archived spectrum', '', (),
            (Device('mca', 'spectrum', 'MCA', 8),), unavailable)
        self.document = dict(definition=describe(self.definition), device='mca', settings={},
            time_s=6, calibrations={}, analysis={'mca': dict(roi=[0, 7], selected=None,
                reference=None, background=None)}, product=dict(format='nuclemu.measurement/1',
                experiment='old', seed=187, devices={'mca': dict(kind='spectrum', channels=8)},
                segments=[dict(acquisition=i + 1, start_s=i * 3, end_s=(i + 1) * 3,
                    settings={}, readings={'mca': [0, i + 5, 0, 0, 0, 0, 0, 0]}) for i in range(2)]))
        self.store.write('old-archive', 'archive', self.document)
        self.database = self.store.directory / 'workbench.sqlite3'
        self.original_database = self.database.read_bytes()
        self.original = convert_archive(self.database, 'old-archive')

    def reopen(self, doc):
        return open_portable(package_bytes(doc), {'old': self.definition}, self.store, lambda: 0)

    def resave(self, lab):
        return archive_package(lab.document(), lab.archive_id, original=lab.portable_archive)

    def test_imported_same_source_copy_does_not_make_original_selection_ambiguous(self):
        doc = deepcopy(self.original)
        original = doc['items'][0]
        copy_id = import_item(doc, self.original, original['id'])
        copied = next(item for item in doc['items'] if item['id'] == copy_id)
        self.assertNotEqual(copy_id, original['id'])
        self.assertEqual(copied['source'], original['source'])
        self.assertEqual(copied['document']['snapshot']['id'], original['document']['snapshot']['id'])
        # Put the copy first so record order cannot serve as an identity rule.
        doc['items'] = [copied] + [item for item in doc['items'] if item['id'] != copy_id]
        lab = self.reopen(doc)
        lab.act(dict(action='select', index=0, device='mca'))
        result = self.resave(lab)
        self.assertEqual(result['analysis']['mca']['selected'], original['id'])
        self.assertEqual(result['items'], doc['items'])
        destination = self.folder / 'resaved.nuclemu'
        save_package(destination, result)
        loaded = load_package(destination)
        again = self.reopen(loaded)
        self.assertTrue(again.readonly)
        self.assertEqual(again.analysis['mca']['selected'], 0)
        self.assertEqual(self.resave(again)['analysis']['mca']['selected'], original['id'])
        self.assertEqual(loaded['items'], doc['items'])
        self.assertEqual(self.database.read_bytes(), self.original_database)

    def test_all_changed_analysis_roles_resolve_original_items_not_same_source_copies(self):
        doc = deepcopy(self.original)
        for original in self.original['items']:
            import_item(doc, self.original, original['id'])
        lab = self.reopen(doc)
        lab.analysis['mca'].update(selected=1, reference=0, background=1)
        result = self.resave(lab)
        self.assertEqual(result['analysis']['mca']['selected'], self.original['items'][1]['id'])
        self.assertEqual(result['analysis']['mca']['reference'], self.original['items'][0]['id'])
        self.assertEqual(result['analysis']['mca']['background'], self.original['items'][1]['id'])
        self.assertEqual(result['items'], doc['items'])

    def test_older_converted_package_without_new_optional_fields_still_resaves(self):
        doc = deepcopy(self.original)
        for item in doc['items']:
            item.pop('response_context', None)
            item['document'].pop('windows', None)
        lab = self.reopen(doc)
        lab.act(dict(action='select', index=1, device='mca'))
        result = self.resave(lab)
        self.assertEqual(result['analysis']['mca']['selected'], doc['items'][1]['id'])
        self.assertEqual(result['items'], doc['items'])
        self.assertEqual(self.reopen(load_package(package_bytes(result))).analysis['mca']['selected'], 1)

    def test_existing_uuid_reference_to_imported_copy_is_preserved(self):
        doc = deepcopy(self.original)
        copy_id = import_item(doc, self.original, doc['items'][0]['id'])
        doc['analysis']['mca']['selected'] = copy_id
        lab = self.reopen(doc)
        result = self.resave(lab)
        self.assertEqual(result['analysis']['mca']['selected'], copy_id)
        self.assertEqual(load_package(package_bytes(result))['analysis']['mca']['selected'], copy_id)
        self.assertEqual(result['items'], doc['items'])

    def test_changed_archive_calibration_does_not_rebind_imported_copy(self):
        from dataclasses import asdict
        from nuclemu.exchange import cache_calibration
        from nuclemu.results import Calibration
        doc = deepcopy(self.original)
        calibration = Calibration('old', 'mca', 8, 0, 0, 7, 7)
        original_id = doc['items'][0]['id']
        calibration_id = cache_calibration(doc, calibration)
        doc['items'][0]['calibration_id'] = calibration_id
        doc['legacy']['document']['calibrations']['mca'] = asdict(calibration)
        source = deepcopy(doc)
        copy_id = import_item(doc, source, original_id)
        copied = deepcopy(next(item for item in doc['items'] if item['id'] == copy_id))
        lab = self.reopen(doc)
        lab.work.lab.calibrations['mca'] = Calibration('old', 'mca', 8, 0, 0, 7, 8)
        result = self.resave(lab)
        actual_original = next(item for item in result['items'] if item['id'] == original_id)
        self.assertNotEqual(actual_original['calibration_id'], calibration_id)
        self.assertEqual(next(item for item in result['items'] if item['id'] == copy_id), copied)


if __name__ == '__main__':
    unittest.main()
