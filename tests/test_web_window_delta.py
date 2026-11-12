"""Per-client counter window cursors preserve complete rows and mutable tails."""

from copy import deepcopy
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from nuclemu.catalog import describe
from nuclemu.experiments.beta import EXPERIMENT
from nuclemu.web import make_server
from nuclemu.web_session import WebLab
from nuclemu.web_store import ArchiveStore


def merge(previous, response):
    result = deepcopy(previous)
    for device, change in response['counter_windows_delta'].items():
        result[device] = result.get(device, [])[:change['start']] + change['windows']
    return result


class WindowDeltaTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.lab = WebLab(EXPERIMENT, describe(EXPERIMENT), 42, ArchiveStore(folder.name), lambda: 0)

    def since(self, previous):
        return self.lab.state(product_cursor=previous['product_cursor'], window_cursor=previous['window_cursor'])

    def test_paused_six_hundred_windows_are_not_serialized_again(self):
        self.lab.work.session.start_group(('counter', 'counter_b'))
        self.lab.work.advance(600)
        self.lab.work.session.stop_group(('counter', 'counter_b'))
        first = self.lab.state()
        self.assertEqual([len(rows) for rows in first['counter_windows'].values()], [600, 600])
        with patch.object(self.lab.work.session, 'instrument_windows', side_effect=AssertionError('unchanged history read')):
            with patch('nuclemu.web_session.window_state', side_effect=AssertionError('unchanged row serialized')):
                current = self.since(first)
                repeated = self.since(current)
        for response in (current, repeated):
            self.assertNotIn('counter_windows', response)
            self.assertEqual(response['counter_windows_delta'], {})
            self.assertEqual(response['product_delta']['segments'], [])
        sizes = {name: len(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())
                 for name, value in [('initial_bytes', first), ('caught_up_bytes', current)]}
        self.assertLess(sizes['caught_up_bytes'], sizes['initial_bytes'] / 5)
        output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
        if output:
            path = Path(output)
            path.mkdir(parents=True, exist_ok=True)
            (path / 'paused-window-payload.json').write_text(json.dumps(sizes, indent=2), encoding='utf-8')

    def test_partial_tail_and_independent_lagging_clients(self):
        self.lab.work.start(device='counter', window_s=3)
        self.lab.work.start(device='counter_b', window_s=5)
        self.lab.work.advance(1)
        first = self.lab.state()
        self.assertFalse(first['counter_windows']['counter'][-1]['complete'])
        self.lab.work.advance(.5)
        self.lab.work.configure({'foil_count': 4})
        current = self.since(first)
        self.assertEqual(current['counter_windows_delta']['counter']['start'], 0)
        self.assertEqual(current['counter_windows_delta']['counter']['windows'][0]['end_exposure_s'], 1.5)
        self.assertEqual(first['counter_windows']['counter'][0]['end_exposure_s'], 1)
        second_client = self.lab.state()
        self.lab.work.advance(1.5)
        updated = self.since(current)
        row = updated['counter_windows_delta']['counter']['windows'][0]
        self.assertTrue(row['complete'])
        self.assertEqual(row['end_exposure_s'], 3)
        self.assertEqual(merge(merge(first['counter_windows'], current), updated), self.lab.state()['counter_windows'])
        self.lab.work.advance(1)
        new_tail = self.since(updated)
        self.assertEqual(new_tail['counter_windows_delta']['counter']['start'], 1)
        self.assertFalse(new_tail['counter_windows_delta']['counter']['windows'][0]['complete'])
        lagged = self.since(second_client)
        self.assertEqual(merge(second_client['counter_windows'], lagged), self.lab.state()['counter_windows'])
        self.lab.work.stop(device='counter')
        self.assertEqual(self.since(new_tail)['counter_windows_delta'], {})
        self.lab.work.start(device='counter')
        self.lab.work.advance(2)
        resumed = self.since(new_tail)
        self.assertEqual(resumed['counter_windows_delta']['counter']['start'], 1)
        self.assertTrue(resumed['counter_windows_delta']['counter']['windows'][0]['complete'])

    def test_clear_load_and_new_session_reset_the_stream(self):
        self.lab.work.start(device='counter')
        self.lab.work.start(device='counter_b', window_s=5)
        self.lab.work.advance(3)
        saved = self.lab.work.snapshot(device='counter')
        first = self.lab.state()
        request = self.lab.work.begin_clear(device='counter')
        self.lab.work.finish_clear(request.token, 'discard', device='counter')
        cleared = self.since(first)
        self.assertEqual(cleared['counter_windows_delta'], {'counter': {'start': 0, 'windows': []}})
        self.lab.work.session.load_measurement('counter', saved)
        loaded = self.since(cleared)
        self.assertEqual(loaded['counter_windows_delta']['counter']['start'], 0)
        self.assertEqual(len(loaded['counter_windows_delta']['counter']['windows']), 3)
        self.assertNotIn('counter_b', loaded['counter_windows_delta'])
        self.lab.work.start(device='counter')
        self.lab.work.advance(1)
        resumed = self.since(loaded)
        self.assertEqual(resumed['counter_windows_delta']['counter']['start'], 3)
        self.assertEqual(len(resumed['counter_windows_delta']['counter']['windows']), 1)
        self.assertEqual(saved.exposure_s, 3)
        other = WebLab(EXPERIMENT, describe(EXPERIMENT), 42, self.lab.store, lambda: 0)
        reset = other.state(window_cursor=resumed['window_cursor'])
        self.assertEqual(reset['counter_windows'], {'counter': [], 'counter_b': []})
        self.assertNotIn('counter_windows_delta', reset)

    def test_missing_or_invalid_cursor_keeps_full_response_compatibility(self):
        self.lab.work.start(device='counter')
        self.lab.work.advance(2)
        for cursor in (None, '', 'not json', '[]', '{"session":"old","devices":{}}'):
            with self.subTest(cursor=cursor):
                response = self.lab.state(window_cursor=cursor)
                self.assertEqual(len(response['counter_windows']['counter']), 2)
                self.assertNotIn('counter_windows_delta', response)


class WindowCursorHttpTests(unittest.TestCase):
    def test_get_and_action_forward_the_window_cursor(self):
        now = 0
        with TemporaryDirectory() as folder, make_server(directory=folder, clock=lambda: now) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            def post(path, data):
                client.request('POST', '/api/' + path, json.dumps(data), {'Content-Type': 'application/json'})
                response = client.getresponse()
                body = response.read()
                self.assertEqual(response.status, 200, body)
                return json.loads(body)
            try:
                opened = post('open', {'experiment': 'beta'})
                post('action', dict(session=opened['id'], action='start_group', component='counter'))
                now = 5
                client.request('GET', '/api/state')
                current = json.loads(client.getresponse().read())
                query = urlencode({key: current[key] for key in ('product_cursor', 'window_cursor')} | {'session': current['id']})
                client.request('GET', '/api/state?' + query)
                response = json.loads(client.getresponse().read())
                self.assertEqual(response['counter_windows_delta'], {})
                response = post('action', dict(session=current['id'], action='snapshot', device='counter',
                                               product_cursor=response['product_cursor'], window_cursor=response['window_cursor']))
                self.assertEqual(response['counter_windows_delta'], {})
                self.assertEqual(len(response['snapshots']), 1)
            finally:
                client.close()
                server.shutdown()
                worker.join()
