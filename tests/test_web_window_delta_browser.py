"""Desktop clients independently recover window history after missed changes."""

import json
import os
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.exchange import load_item

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class WindowDeltaBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def action(self, name, click):
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == name) as response:
            click()
        self.assertTrue(response.value.ok, response.value.text())
        return response.value.json()

    def test_long_paused_history_reconnect_clear_load_and_download(self):
        self.enter('beta')
        fixtures.enable_output(self)
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 600
        rows = self.page.locator('.counter-window[data-device=counter] tbody tr')
        expect(rows).to_have_count(600)
        expect(self.page.locator('.counter-window[data-device=counter_b] tbody tr')).to_have_count(600)
        self.action('stop_group', lambda: self.page.locator('#stop').click())
        with self.page.expect_response(lambda r: '/api/state?' in r.url and 'window_cursor=' in r.url) as polled:
            pass
        paused = polled.value.json()
        self.assertNotIn('counter_windows', paused)
        self.assertEqual(paused['counter_windows_delta'], {})
        full = self.page.request.get(self.url + '/api/state').json()
        self.assertLess(len(polled.value.body()), len(json.dumps(full).encode()) / 5)
        saved = self.action('snapshot_group', lambda: fixtures.measurement_operation(self.page, 'save'))

        peer = self.browser.new_page(viewport={'width': 1366, 'height': 768})
        self.addCleanup(peer.close)
        peer.goto(self.url + '/lab/beta/#instrument')
        peer_rows = peer.locator('.counter-window[data-device=counter] tbody tr')
        expect(peer_rows).to_have_count(600)
        peer.route('**/api/state?*', lambda route: route.abort())
        expect(peer.locator('#error')).to_be_visible()
        self.action('begin_clear_group', lambda: fixtures.measurement_operation(self.page, 'clear'))
        self.action('finish_clear_group', lambda: self.page.locator('#clear-discard').click())
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('暂无逐窗读数')
        fixtures.measurement_operation(self.page, 'cache')
        expect(self.page.locator('#measurement-load')).to_be_visible()
        self.action('load_measurement', lambda: self.page.locator('#measurement-confirm').click())
        expect(rows).to_have_count(600)
        with peer.expect_response(lambda r: '/api/state?' in r.url) as recovered:
            peer.unroute('**/api/state?*')
        delta = recovered.value.json()
        self.assertEqual(delta['counter_windows_delta']['counter']['start'], 0)
        self.assertEqual(len(delta['counter_windows_delta']['counter']['windows']), 600)
        self.assertEqual(len(delta['counter_windows_delta']['counter_b']['windows']), 600)
        expect(peer_rows).to_have_count(600)
        expect(peer.locator('#error')).not_to_be_visible()
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 601
        expect(rows).to_have_count(601)
        expect(peer_rows).to_have_count(601)
        self.action('stop_group', lambda: self.page.locator('#stop').click())
        self.screenshot('window-delta-recovered-601')
        self.page.locator('[data-page=records]').click()
        self.page.locator('#products .product input').check()
        with self.page.expect_download() as downloading:
            self.page.locator('#export').click()
        path = Path(self.folder.name, downloading.value.suggested_filename)
        downloading.value.save_as(path)
        documents = {item['document']['snapshot']['device']: item['document']
                     for item in load_item(path.read_bytes())['items'] if item['kind'] == 'measurement'}
        self.assertEqual(set(documents), {'counter', 'counter_b'})
        for device, document in documents.items():
            self.assertEqual(len(document['windows']), 600)
            self.assertEqual(document['snapshot']['exposure_s'], 600)
            self.assertEqual([sum(w['counts'][0] for w in document['windows'])], full['instruments'][device]['counts'])
        output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / path.name).write_bytes(path.read_bytes())
            (directory / 'browser-window-delta.json').write_text(json.dumps({
                'full_bytes': len(json.dumps(full).encode()), 'paused_bytes': len(polled.value.body()),
                'recovered_windows': len(delta['counter_windows_delta']['counter']['windows']),
                'saved_measurements': {device: dict(windows=len(document['windows']),
                    counts=[sum(w['counts'][0] for w in document['windows'])]) for device, document in documents.items()},
                'saved_response_cursor': saved['window_cursor'],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
