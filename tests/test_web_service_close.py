"""Native close rounds preserve files, measurements and newer browser sessions."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from nuclemu.exchange import load_package
from nuclemu.web_service import StaleCloseError, WorkbenchService
from tests.test_web_instrument_records import course


class ServiceCloseTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        with patch('nuclemu.web.discover', return_value={'boxes': course()}):
            self.service = WorkbenchService(directory=self.folder.name, clock=lambda: self.now).start()
            self.service.wait_ready(3)
        self.addCleanup(self.stop)
        self.server = self.service._server
        self.app = self.server.app
        self.target = Path(self.folder.name) / '实验.nuclemu'

    def stop(self):
        self.service.stop(force=True)
        self.assertTrue(self.service.join(3))

    def request(self, route, **data):
        with self.server.app_lock:
            return self.app.request(route, data)

    def action(self, action, **data):
        return self.request('/api/action', session=self.app.lab.id, action=action, **data)

    def open_cached(self):
        self.request('/api/open', experiment='boxes')
        self.action('output', output='detector', enabled=True)
        self.action('window_config', component='pair', device='b', window_s=5)
        self.action('start_group', component='pair')
        self.now = 3
        self.action('snapshot_group', component='pair', device='a', title='3 seconds',
                    acquisitions={'a': 1, 'b': 1})
        self.now = 5

    def test_idle_begin_stops_and_pre_start_begin_cancels(self):
        self.assertIsNone(self.service.begin_close())
        self.assertFalse(self.server.accepting_requests)
        self.assertTrue(self.service.join(3))
        other = WorkbenchService()
        self.assertIsNone(other.begin_close())
        self.assertEqual(other.status().phase, 'stopped')
        self.assertIsNone(other.begin_close())
        self.assertEqual(other.status().phase, 'stopped')

    def test_failed_service_close_preserves_terminal_phase(self):
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            other = WorkbenchService(port=listener.getsockname()[1], directory=self.folder.name).start()
            with self.assertRaises(OSError):
                other.wait_ready(3)
            self.assertTrue(other.join(3))
            self.assertEqual(other.status().phase, 'failed')
            self.assertIsNone(other.begin_close())
            self.assertEqual(other.status().phase, 'failed')
            self.assertTrue(other.join(0))

    def test_idle_begin_rejects_an_already_accepted_browser_open(self):
        from http.client import HTTPConnection
        from nuclemu import web
        import json
        accepted, results = Event(), []
        original = web.WorkbenchHandler.do_POST
        def observed(handler):
            accepted.set()
            return original(handler)
        def browser_open():
            connection = HTTPConnection(*self.server.server_address, timeout=3)
            try:
                connection.request('POST', '/api/open', json.dumps(dict(experiment='boxes')),
                                   {'Content-Type': 'application/json'})
                response = connection.getresponse()
                results.append(response.status)
                response.read()
            finally:
                connection.close()
        with patch.object(web.WorkbenchHandler, 'do_POST', observed):
            with self.server.app_lock:
                thread = Thread(target=browser_open)
                thread.start()
                self.assertTrue(accepted.wait(2))
                self.assertIsNone(self.service.begin_close())
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [503])
        self.assertIsNone(self.app.lab)

    def test_begin_reuses_browser_confirmation_and_cancel_resumes_running_gates(self):
        self.open_cached()
        token = self.action('freeze')['confirmation_id']
        context = self.service.begin_close()
        self.assertEqual(context.confirmation_id, token)
        self.assertEqual(context.session, self.app.lab.id)
        self.assertTrue(context.has_uncached)
        self.assertFalse(context.readonly)
        self.assertTrue(context.filename.endswith('.nuclemu'))
        self.now = 30
        self.service.cancel_close(context)
        self.now = 31
        with self.server.app_lock:
            state = self.app.state()
        self.assertFalse(state['frozen'])
        self.assertTrue(state['running'])
        self.assertEqual(state['instruments']['b']['exposure_s'], 6)
        self.assertEqual(len(self.app.lab.work.session.snapshots), 2)
        self.assertTrue(self.server.accepting_requests)

    def test_save_writes_cached_three_seconds_and_stops_after_replace(self):
        self.open_cached()
        context = self.service.begin_close()
        self.service.save_close(context, self.target)
        self.assertTrue(self.service.join(3))
        self.assertIsNone(self.app.lab)
        self.assertFalse(self.server.accepting_requests)
        doc = load_package(self.target)
        self.assertEqual(len(doc['items']), 2)
        for item in doc['items']:
            self.assertEqual(item['document']['snapshot']['exposure_s'], 3)
        self.assertFalse(list(self.target.parent.glob('.*.tmp')))

    def test_write_failure_keeps_original_cache_round_and_allows_retry(self):
        self.open_cached()
        context = self.service.begin_close()
        snapshots = self.app.lab.work.session.snapshots
        self.target.write_bytes(b'original')
        with patch('os.fsync', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.service.save_close(context, self.target)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(self.app.lab.work.session.snapshots, snapshots)
        self.assertTrue(self.app.lab.frozen)
        self.assertEqual(self.app.lab.confirmation_id, context.confirmation_id)
        self.assertFalse(list(self.target.parent.glob('.*.tmp')))
        self.service.save_close(context, self.target)
        self.assertEqual(len(load_package(self.target)['items']), 2)

    def test_replace_failure_can_return_to_running_session(self):
        self.open_cached()
        context = self.service.begin_close()
        self.target.write_bytes(b'original')
        with patch('os.replace', side_effect=OSError('access denied')):
            with self.assertRaisesRegex(OSError, 'access denied'):
                self.service.save_close(context, self.target)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.service.cancel_close(context)
        self.assertFalse(self.app.lab.frozen)
        self.assertEqual(self.service.status().phase, 'ready')

    def test_export_failure_keeps_confirmation_and_file(self):
        self.open_cached()
        context = self.service.begin_close()
        self.target.write_bytes(b'original')
        with patch.object(self.app.lab.exchange, 'download_package', side_effect=OSError('encode failed')):
            with self.assertRaisesRegex(OSError, 'encode failed'):
                self.service.save_close(context, self.target)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(self.app.lab.confirmation_id, context.confirmation_id)
        self.service.cancel_close(context)

    def test_old_context_cannot_cancel_discard_or_save_a_new_confirmation(self):
        self.open_cached()
        old = self.service.begin_close()
        self.action('continue', confirmation_id=old.confirmation_id)
        new = self.service.begin_close()
        self.assertNotEqual(old.confirmation_id, new.confirmation_id)
        for operation in (self.service.cancel_close, self.service.discard_close,
                          lambda context: self.service.save_close(context, self.target)):
            with self.assertRaisesRegex(StaleCloseError, '过期'):
                operation(old)
        self.assertEqual(self.app.lab.confirmation_id, new.confirmation_id)
        self.assertFalse(self.target.exists())

    def test_slow_write_is_unlocked_and_rechecks_before_overwriting_or_closing_new_session(self):
        self.open_cached()
        context = self.service.begin_close()
        self.target.write_bytes(b'original')
        entered, release = Event(), Event()
        errors = []
        def slow_sync(fd):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test writer not released')
        def save():
            try:
                self.service.save_close(context, self.target)
            except Exception as error:
                errors.append(error)
        with patch('os.fsync', side_effect=slow_sync):
            thread = Thread(target=save)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.action('continue', confirmation_id=context.confirmation_id)
                token = self.action('freeze')['confirmation_id']
                self.action('discard', confirmation_id=token)
                state = self.request('/api/open', experiment='boxes', seed=99)
                new_id = state['id']
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertEqual(self.app.lab.id, new_id)
        self.assertFalse(self.app.lab.frozen)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(self.service.status().phase, 'ready')
        self.assertFalse(list(self.target.parent.glob('.*.tmp')))

    def test_discard_closes_confirmed_session_and_gates_new_opens(self):
        self.open_cached()
        context = self.service.begin_close()
        self.service.discard_close(context)
        self.assertIsNone(self.app.lab)
        self.assertFalse(self.server.accepting_requests)
        self.assertTrue(self.service.join(3))

    def test_readonly_archive_is_converted_without_mutating_source(self):
        from nuclemu.web_session import WebLab
        self.open_cached()
        with self.server.app_lock:
            document = deepcopy(self.app.lab.document())
            self.app.store.write('original', 'archive', document)
            self.app.lab = WebLab.read('original', self.app.store, lambda: self.now)
        original = self.app.store.read('original')
        context = self.service.begin_close()
        self.assertTrue(context.readonly)
        self.assertFalse(context.has_uncached)
        self.service.save_close(context, self.target)
        doc = load_package(self.target)
        self.assertEqual(doc['legacy']['document']['product'], original['product'])
        self.assertEqual(self.app.store.read('original'), original)

    def test_ordinary_export_value_error_is_not_stale_and_can_cancel(self):
        self.open_cached()
        context = self.service.begin_close()
        with patch.object(self.app.lab, 'portable_download', side_effect=ValueError('bad export')):
            with self.assertRaisesRegex(ValueError, 'bad export') as raised:
                self.service.save_close(context, self.target)
        self.assertNotIsInstance(raised.exception, StaleCloseError)
        self.service.cancel_close(context)
        self.assertFalse(self.app.lab.frozen)

    def test_converted_archive_keeps_ids_extra_items_and_updated_analysis(self):
        from base64 import b64encode
        from uuid import uuid4
        from nuclemu.exchange import archive_package, package_bytes
        self.open_cached()
        with self.server.app_lock:
            original = archive_package(deepcopy(self.app.lab.document()), 'old-id')
            extra = deepcopy(original['items'][0])
            extra['id'] = str(uuid4())
            extra['source'] = dict(package=str(uuid4()), item=str(uuid4()))
            original['items'].append(extra)
            self.app.lab = None
        self.request('/api/open_package', file=b64encode(package_bytes(original)).decode())
        with self.server.app_lock:
            self.app.lab.analysis['a']['rate_axis'] = True
            self.app.lab.analysis['a']['selected'] = 0
        context = self.service.begin_close()
        self.service.save_close(context, self.target)
        actual = load_package(self.target)
        self.assertEqual(actual['id'], original['id'])
        self.assertEqual(actual['items'], original['items'])
        self.assertTrue(actual['legacy']['document']['analysis']['a']['rate_axis'])
        self.assertTrue(actual['analysis']['a']['rate_axis'])
        target = next(item for item in original['items'] if item.get('source', {}).get('archive') == 'old-id'
            and 'a' in item['document']['devices'] and item['document']['snapshot']['id'] == 1)
        self.assertEqual(actual['analysis']['a']['selected'], target['id'])

    def test_legacy_live_draft_cleanup_failure_reports_saved_success(self):
        from nuclemu.catalog import describe
        from nuclemu.core import Device, Experiment
        from nuclemu.web_session import WebLab
        definition = Experiment('old', 'Old', '', (), (Device('c', 'counter', 'C'),),
            lambda settings, start, end, rng: {'c': (1,)})
        with self.server.app_lock:
            self.app.lab = WebLab(definition, describe(definition), 0, self.app.store, lambda: self.now)
            self.app.lab.work.session.start(10)
            self.now = 3
            self.app.state()
        context = self.service.begin_close()
        self.target.write_bytes(b'original')
        with patch.object(self.app.store, 'remove', side_effect=OSError('cannot clean draft')):
            result = self.service.save_close(context, self.target)
        self.assertEqual(result.path, str(self.target.absolute()))
        self.assertIn('文件已保存', result.warning)
        self.assertIn('cannot clean draft', result.warning)
        self.assertEqual(load_package(self.target)['legacy']['document']['time_s'], 3)
        self.assertIsNone(self.app.lab)
        self.assertTrue(self.service.join(3))

    def test_exit_save_rejects_working_database_and_hardlink_without_losing_archives(self):
        import os
        from nuclemu.web_session import WebLab
        self.open_cached()
        with self.server.app_lock:
            document = deepcopy(self.app.lab.document())
            self.app.store.write('first', 'archive', document)
            self.app.store.write('second', 'archive', document)
            self.app.lab = WebLab.read('first', self.app.store, lambda: self.now)
        database = self.app.store.directory / 'workbench.sqlite3'
        archived = self.app.store.read('first')
        alias = database.with_name('database-alias.nuclemu')
        os.link(database, alias)
        context = self.service.begin_close()
        original = database.read_bytes()
        for target in (database, alias):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, '工作库'):
                    self.service.save_close(context, target)
                self.assertEqual(database.read_bytes(), original)
                self.assertEqual(self.app.store.read('first'), archived)
                self.assertEqual(self.app.store.read('second'), archived)
                self.assertEqual(self.app.lab.confirmation_id, context.confirmation_id)
                self.assertEqual(self.service.status().phase, 'ready')
        self.service.save_close(context, self.target)
        self.assertTrue(self.service.join(3))
        self.assertEqual(load_package(self.target)['legacy']['document']['product'], archived['product'])

    def test_exit_save_protects_database_file_symlink_target(self):
        self.open_cached()
        self.app.store.list()
        backing = Path(self.folder.name) / 'actual-database.sqlite3'
        database = self.app.store.database_path
        database.rename(backing)
        try:
            database.symlink_to(backing)
        except OSError as error:
            backing.rename(database)
            self.skipTest(f'Cannot create database symlink on this filesystem: {error}')
        context = self.service.begin_close()
        original = backing.read_bytes()
        with self.assertRaisesRegex(ValueError, '工作库'):
            self.service.save_close(context, backing)
        self.assertEqual(backing.read_bytes(), original)
        self.service.cancel_close(context)
        self.assertFalse(self.app.lab.frozen)

    def test_modern_exit_save_does_not_open_or_create_unavailable_working_database(self):
        self.open_cached()
        database = self.app.store.database_path
        database.unlink(missing_ok=True)
        with patch.object(self.app.store, '_connect', side_effect=OSError('working directory is read-only')) as connect:
            context = self.service.begin_close()
            self.service.save_close(context, self.target)
            connect.assert_not_called()
        self.assertFalse(database.exists())
        self.assertEqual(len(load_package(self.target)['items']), 2)

    def test_exit_save_rechecks_database_alias_after_slow_file_write(self):
        import os
        self.open_cached()
        self.app.store.list()
        context = self.service.begin_close()
        database = self.app.store.database_path
        original = database.read_bytes()
        sync = os.fsync
        def alias_during_write(fd):
            os.link(database, self.target)
            sync(fd)
        with patch('os.fsync', side_effect=alias_during_write):
            with self.assertRaisesRegex(ValueError, '工作库'):
                self.service.save_close(context, self.target)
        self.assertEqual(database.read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(list(self.target.parent.glob('.*.tmp')))
        self.service.cancel_close(context)
        self.assertFalse(self.app.lab.frozen)

    def test_legacy_live_exit_prompt_matches_whole_session_save(self):
        from nuclemu.catalog import describe
        from nuclemu.core import Device, Experiment
        from nuclemu.web_session import WebLab
        definition = Experiment('old', 'Old', '', (), (Device('c', 'counter', 'C'),),
            lambda settings, start, end, rng: {'c': (round(end - start),)})
        with self.server.app_lock:
            self.app.lab = WebLab(definition, describe(definition), 0, self.app.store, lambda: self.now)
            self.app.lab.work.session.start(10)
            self.now = 3
            self.app.state()
        context = self.service.begin_close()
        self.assertFalse(context.has_uncached)
        self.service.save_close(context, self.target)
        segments = load_package(self.target)['legacy']['document']['product']['segments']
        self.assertEqual(sum(segment['end_s'] - segment['start_s'] for segment in segments), 3)
        self.assertEqual(sum(segment['readings']['c'][0] for segment in segments), 3)

    def test_readonly_resave_normalizes_calibration_then_keeps_changed_calibration(self):
        from base64 import b64encode
        from nuclemu.catalog import describe
        from nuclemu.core import Device, Experiment
        from nuclemu.exchange import archive_package, package_bytes
        from nuclemu.results import Calibration
        definition = Experiment('spec', 'Spectrum archive', '', (),
            (Device('mca', 'spectrum', 'MCA', 8),), lambda *args: {})
        calibration = Calibration('spec', 'mca', 8, 0, 0, 7, 7)
        fields = calibration.document()
        del fields['format'], fields['unit']
        old = dict(definition=describe(definition), time_s=3, settings={}, device='mca',
            analysis={'mca': dict(roi=[0, 7], selected=0, reference=None, background=None)},
            calibrations={'mca': fields}, product=dict(format='nuclemu.measurement/1',
                experiment='spec', seed=7, devices={'mca': dict(kind='spectrum', channels=8)},
                segments=[dict(acquisition=1, start_s=0, end_s=3, settings={},
                               readings={'mca': [0, 0, 5, 0, 0, 0, 0, 0]})]))
        original = load_package(package_bytes(archive_package(old, 'old-spec')))
        self.request('/api/open_package', file=b64encode(package_bytes(original)).decode())
        with self.server.app_lock:
            unchanged = archive_package(self.app.lab.document(), self.app.lab.archive_id,
                                        original=self.app.lab.portable_archive)
            self.assertEqual(unchanged['items'], original['items'])
            self.app.lab.work.lab.calibrations['mca'] = Calibration('spec', 'mca', 8, 0, 0, 7, 8)
        context = self.service.begin_close()
        self.service.save_close(context, self.target)
        actual = load_package(self.target)
        measurement = next(item for item in actual['items'] if item['kind'] == 'measurement')
        old_measurement = next(item for item in original['items'] if item['kind'] == 'measurement')
        self.assertEqual(measurement['id'], old_measurement['id'])
        self.assertEqual(measurement['source'], old_measurement['source'])
        self.assertEqual(measurement['document'], old_measurement['document'])
        calibration_item = next(item for item in actual['items'] if item['id'] == measurement['calibration_id'])
        self.assertEqual(Calibration.from_document(calibration_item['document']).energy(7), 8)
        self.assertEqual(actual['legacy']['document']['calibrations']['mca']['energy2'], 8)


if __name__ == '__main__':
    unittest.main()
