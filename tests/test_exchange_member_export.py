"""Selecting a grouped member for export must retain the complete saved instrument."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from nuclemu.core import Session
from nuclemu.experiments.beta import EXPERIMENT
from nuclemu.exchange import (batch_download, capture_session, decode_measurements,
    export_item, import_item, load_item, load_package, package_bytes)
from test_cli import invoke
from test_exchange_group import saved_set


class MemberExportTests(unittest.TestCase):
    def test_member_single_and_batch_exports_keep_group_name_source_and_partial_window(self):
        _, doc, primary = saved_set()
        member = doc['items'][1]['id']
        before = deepcopy(doc)
        for fmt in ('csv', 'json'):
            with self.subTest(format=fmt):
                self.assertEqual(export_item(doc, member, fmt), export_item(doc, primary, fmt))
                name, _, data = batch_download(doc, [dict(id=member, format=fmt)])
                self.assertTrue(name.endswith('_counts.' + fmt), name)
                bundle = load_item(data)
                self.assertEqual(bundle['items'], doc['items'])
                self.assertEqual(load_item(export_item(bundle, member, fmt))['items'], doc['items'])
                decoded = decode_measurements(bundle, EXPERIMENT, ('counter', 'counter_b'))
                self.assertEqual([s.snapshot.exposure_s for s in decoded], [3, 3])
                self.assertEqual([len(s.snapshot.windows) for s in decoded], [3, 1])
                self.assertFalse(decoded[1].snapshot.windows[0].complete)
                # Export does not relax the separate import boundary.
                with self.assertRaisesRegex(ValueError, 'companion'):
                    import_item(capture_session(Session(EXPERIMENT)), bundle, member)
        _, _, zipped = batch_download(doc, [dict(id=member, format='csv'), dict(id=member, format='json')])
        with ZipFile(BytesIO(zipped)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            for name in archive.namelist():
                self.assertIn('_counts.', name)
                self.assertEqual(load_item(archive.read(name))['items'], doc['items'])
        self.assertEqual(doc, before)

    def test_native_single_window_stays_single_on_export_and_import(self):
        source = Session(EXPERIMENT)
        source.start(1, device='counter_b')
        source.advance(1)
        source.snapshot('counter_b')
        doc = capture_session(source)
        identity = doc['items'][0]['id']
        for fmt in ('csv', 'json'):
            name, _, data = batch_download(doc, [dict(id=identity, format=fmt)])
            self.assertTrue(name.endswith('_counts-B.' + fmt), name)
            bundle = load_item(data)
            self.assertEqual(bundle['items'], doc['items'])
            target = capture_session(Session(EXPERIMENT))
            import_item(target, bundle, identity)
            self.assertEqual(len(target['items']), 1)
            self.assertNotIn('group', target['items'][0])

    def test_actual_cli_member_exports_import_as_complete_records_in_both_formats(self):
        _, doc, primary = saved_set()
        member = doc['items'][1]['id']
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / 'source.nuclemu'
            original = package_bytes(doc)
            source.write_bytes(original)
            target = folder / 'empty.nuclemu'
            target.write_bytes(package_bytes(capture_session(Session(EXPERIMENT))))
            for fmt in ('csv', 'json'):
                path = folder / ('selected-b.' + fmt)
                result = invoke('files', 'export', str(source), '--item', member, '--output', str(path))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(load_item(path)['items'], doc['items'])
                inspected = invoke('files', 'inspect', str(path))
                self.assertEqual(inspected.returncode, 0, inspected.stderr)
                record = json.loads(inspected.stdout)['records'][0]
                self.assertEqual(record['id'], primary)
                output = folder / ('imported-' + fmt + '.nuclemu')
                result = invoke('files', 'import', str(target), str(path), '--item', record['id'], '--output', str(output))
                self.assertEqual(result.returncode, 0, result.stderr)
                items = load_package(output)['items']
                self.assertEqual([i['document'] for i in items], [i['document'] for i in doc['items']])
                self.assertEqual([i['source'] for i in items], [i['source'] for i in doc['items']])
                self.assertEqual(items[0]['group']['items'], [i['id'] for i in items])
            zipped = folder / 'selected.zip'
            result = invoke('files', 'batch-export', str(source), '--item', member + ':csv',
                            '--item', member + ':json', '--output', str(zipped))
            self.assertEqual(result.returncode, 0, result.stderr)
            with ZipFile(zipped) as archive:
                for name in archive.namelist():
                    self.assertIn('_counts.', name)
                    self.assertEqual(load_item(archive.read(name))['items'], doc['items'])
            self.assertEqual(source.read_bytes(), original)
