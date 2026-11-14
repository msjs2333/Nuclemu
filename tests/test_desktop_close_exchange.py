"""Native close files cross the HTTP service, CLI and a fresh service intact."""

from base64 import b64encode
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from urllib.request import Request, urlopen

from nuclemu.catalog import describe
from nuclemu.core import Device, Experiment, Parameter
from nuclemu.exchange import load_package
from nuclemu.results import Calibration
from nuclemu.web_service import WorkbenchService
from nuclemu.web_store import ArchiveStore


class ServiceClient:
    """A real listener with a controllable physical clock, no desktop dependency."""

    def __init__(self, directory):
        self.now = 0
        self.service = WorkbenchService(directory=directory, clock=lambda: self.now).start()
        self.url = self.service.wait_ready(5)
        self.session = None

    def close(self):
        self.service.stop(force=True)
        if not self.service.join(5):
            raise AssertionError('Service did not stop')

    def post(self, route, *, raw=False, **data):
        request = Request(self.url + 'api/' + route, json.dumps(data).encode(),
                          {'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            body = response.read()
        return body if raw else json.loads(body)

    def state(self):
        with urlopen(self.url + 'api/state', timeout=5) as response:
            return json.load(response)

    def action(self, action, **data):
        return self.post('action', session=self.session, action=action, **data)

    def cached_sample(self, course):
        state = self.post('open', experiment=course, seed=187)
        self.session = state['id']
        self.action('configure', values={'source_present': 1})
        for output in state['definition']['outputs']:
            self.action('output', output=output['id'], enabled=True)
        if course == 'alpha':
            state = self.state()
            self.action('load_calibration', device='mca', calibration_context=state['calibration_context'],
                        calibration=Calibration('alpha', 'mca', 1024, 0, 0, 1000, 6).document())
            state = self.state()
            self.action('cache_calibration', device='mca', calibration_context=state['calibration_context'],
                        title='Energy calibration')
            self.action('start', device='mca')
        else:
            for device, seconds in (('counter', 1), ('counter_b', 5)):
                self.action('window_config', component='counter', device=device, window_s=seconds)
            self.action('start_group', component='counter')
        self.now = 3
        state = self.state()
        if course == 'alpha':
            self.action('snapshot', device='mca')
        else:
            self.action('snapshot_group', component='counter', device='counter', title='Three seconds',
                        acquisitions={d: state['instruments'][d]['acquisition']
                                      for d in ('counter', 'counter_b')})
        cached = load_package(self.post('download', raw=True, session=self.session, scope='experiment'))
        self.now = 5
        live = self.state()
        return cached, live


class DesktopCloseExchangeTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.clients = []
        self.addCleanup(self.stop_clients)

    def stop_clients(self):
        for client in reversed(self.clients):
            client.close()

    def client(self):
        client = ServiceClient(self.folder / f'store-{len(self.clients)}')
        self.clients.append(client)
        return client

    def inspect(self, path):
        result = subprocess.run([sys.executable, '-m', 'nuclemu', 'files', 'inspect', str(path)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def reopen(self, path):
        client = self.client()
        state = client.post('open_package', file=b64encode(path.read_bytes()).decode())
        client.session = state['id']
        return client, state

    def assert_cached_items_reopen(self, path, expected):
        document = load_package(path)
        self.assertEqual(document['items'], expected['items'])
        listing = self.inspect(path)
        self.assertEqual({row['id'] for row in listing['items']}, {row['id'] for row in document['items']})
        client, state = self.reopen(path)
        self.assertTrue(state['portable_loaded'])
        self.assertFalse(state['any_running'])
        for item in document['items']:
            if item['kind'] != 'measurement':
                continue
            product = item['document']
            device = product['snapshot']['device']
            client.action('device', device=device)
            state = client.action('select', device=device, item_id=item['id'])
            self.assertEqual(state['selected_observation']['counts'],
                             [sum(row['counts'][i] for row in product['windows'])
                              for i in range(product['devices'][device]['channels'])])
            self.assertEqual(state['selected_observation']['exposure_s'], 3)
            self.assertEqual(state['selected_observation']['segments'], product['segments'])
            if device == 'mca':
                calibration = next(row['document'] for row in document['items']
                                   if row['id'] == item['calibration_id'])
                self.assertEqual(state['calibration'], json.loads(json.dumps(asdict(Calibration.from_document(calibration)))))
            exported = path.with_name(device + '.json')
            result = subprocess.run([sys.executable, '-m', 'nuclemu', 'files', 'export', str(path),
                                     '--item', item['id'], '--output', str(exported)],
                                    capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(product, [row['document'] for row in json.loads(exported.read_text(encoding='utf-8'))['items']])
        downloaded = load_package(client.post('download', raw=True, session=client.session, scope='experiment'))
        self.assertEqual(downloaded['items'], document['items'])
        if document['definition']['id'] == 'beta':
            choice = client.post('inspect_measurement', session=client.session, component='counter', device='counter')
            record = next(row for row in listing['records'] if row['kind'] == 'measurement')
            state = client.action('load_measurement', token=choice['token'], item_id=record['id'], overwrite=True)
            for item in document['items']:
                device = item['document']['snapshot']['device']
                expected_windows = item['document']['windows']
                actual_windows = state['counter_windows'][device]
                # Loading into a new instrument creates a local acquisition id;
                # the source identity was checked in the unchanged file above.
                keys = ('device', 'number', 'start_exposure_s', 'end_exposure_s', 'counts', 'complete')
                self.assertEqual([{k: row[k] for k in keys} for row in actual_windows],
                                 [{k: row[k] for k in keys} for row in expected_windows])
                self.assertEqual(state['instruments'][device]['exposure_s'], 3)
                self.assertTrue(all(row['acquisition'] == state['instruments'][device]['acquisition']
                                    for row in actual_windows))
        return document

    def test_three_second_cache_survives_native_close_at_five_cli_and_new_service(self):
        for course in ('alpha', 'beta'):
            with self.subTest(course=course):
                client = self.client()
                expected, live = client.cached_sample(course)
                self.assertTrue(live['any_running'])
                self.assertTrue(all(row['exposure_s'] == 5 for row in live['instruments'].values()))
                context = client.service.begin_close()
                self.assertEqual(context.session, client.session)
                self.assertFalse(context.readonly)
                self.assertTrue(context.has_uncached)
                self.assertTrue(context.filename.endswith('.nuclemu'))
                path = self.folder / f'{course}.nuclemu'
                result = client.service.save_close(context, path)
                self.assertEqual(Path(result.path), path)
                self.assertIsNone(result.warning)
                self.assertTrue(client.service.join(5))
                self.assertEqual(client.service.status().phase, 'stopped')
                document = self.assert_cached_items_reopen(path, expected)
                rows = [i['document'] for i in document['items'] if i['kind'] == 'measurement']
                self.assertTrue(all(row['snapshot']['exposure_s'] == 3 for row in rows))
                if course == 'beta':
                    by_device = {r['snapshot']['device']: r for r in rows}
                    self.assertEqual(len(by_device['counter']['windows']), 3)
                    self.assertTrue(all(row['complete'] for row in by_device['counter']['windows']))
                    self.assertEqual(len(by_device['counter_b']['windows']), 1)
                    self.assertFalse(by_device['counter_b']['windows'][0]['complete'])

    def test_readonly_archive_and_converted_file_close_remain_readonly_and_keep_data(self):
        client = self.client()
        definition = Experiment('alpha', 'Archived spectrum', '',
            (Parameter('foil_um', 'Total thickness', 'µm', 0, 0, 40),),
            (Device('mca', 'spectrum', 'MCA', 1024),), lambda *args: {})
        counts = [0] * 1024
        counts[500] = 172
        product = dict(format='nuclemu.measurement/1', experiment='alpha', seed=187,
            devices={'mca': {'kind': 'spectrum', 'channels': 1024}}, segments=[dict(
                acquisition=1, start_s=0, end_s=2.25, settings={'foil_um': 2.5}, readings={'mca': counts})])
        document = dict(definition=describe(definition), time_s=2.25, settings={'foil_um': 2.5},
            device='mca', analysis={'mca': dict(roi=[0, 1023], selected=0, reference=None, background=None)},
            calibrations={'mca': asdict(Calibration('alpha', 'mca', 1024, 0, 0, 1000, 6))}, product=product)
        store = ArchiveStore(client.service.directory)
        store.write('archived-alpha', 'archive', document)
        database = Path(client.service.directory) / 'workbench.sqlite3'
        original = database.read_bytes()
        state = client.post('open', archive='archived-alpha')
        client.session = state['id']
        self.assertTrue(state['readonly'])
        previous_package = None
        for label in ('store', 'portable'):
            with self.subTest(source=label):
                context = client.service.begin_close()
                self.assertTrue(context.readonly)
                path = self.folder / f'readonly-{label}.nuclemu'
                result = client.service.save_close(context, path)
                self.assertEqual(Path(result.path), path)
                self.assertIsNone(result.warning)
                self.assertTrue(client.service.join(5))
                self.inspect(path)
                saved = load_package(path)
                self.assertEqual(saved['legacy']['document']['product'], product)
                if previous_package is not None:
                    self.assertEqual(saved['id'], previous_package['id'])
                    self.assertEqual(saved['items'], previous_package['items'])
                previous_package = saved
                client, state = self.reopen(path)
                self.assertTrue(state['readonly'])
                self.assertFalse(state['any_running'])
                self.assertEqual((state['readout']['counts'], state['readout']['exposure_s']), (172, 2.25))
                self.assertEqual(state['calibration']['energy2'], 6)
                self.assertEqual(state['settings'], {'foil_um': 2.5})
        self.assertEqual(database.read_bytes(), original)
