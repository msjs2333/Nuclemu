"""Desktop review paths through visible controls and real file downloads."""

import json
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.exchange import export_item, load_package

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class DesktopRevisionTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def start(self):
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') in ('start', 'start_group')) as started:
            self.page.locator('#start').click()
        self.assertTrue(started.value.ok, started.value.text())

    def beta(self):
        self.enter('beta')
        self.page.locator('[name=source_present]').select_option('1')
        self.page.get_by_role('button', name='应用参数', exact=True).click()
        self.page.locator('#output-beta_detector').check()
        self.page.locator('[data-page=instrument]').click()

    def test_refresh_restores_clear_confirmation_and_other_window_continues(self):
        self.beta()
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('10')
        self.page.locator('#apply-acquisition').click()
        self.start()
        self.now = 3
        fixtures.expect_counter_exposure(self.page, 3)
        fixtures.measurement_operation(self.page, 'clear')
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        token = self.state()['clear_confirmation']['token']
        self.page.reload()
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.assertEqual(self.state()['clear_confirmation']['token'], token)
        self.now = 5.5
        self.page.locator('#clear-cancel').click()
        expect(self.page.locator('#clear-confirm')).not_to_be_visible()
        state = self.state()
        self.assertEqual(state['instruments']['counter']['exposure_s'], 3)
        self.assertEqual(state['instruments']['counter']['remaining_s'], 7)
        self.assertEqual(state['instruments']['counter_b']['exposure_s'], 5.5)
        self.screenshot('beta-refresh-clear-restored')
        self.now = 6
        fixtures.expect_counter_exposure(self.page, 3.5)

    def test_dual_windows_cache_and_files_load_only_target_then_append(self):
        self.beta()
        self.page.locator('#window-size-counter').fill('1')
        self.page.locator('#window-size-counter_b').fill('5')
        self.page.locator('#window-size-counter_b').press('Tab')
        self.start()
        self.now = 3
        fixtures.expect_counter_exposure(self.page, 3)
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'snapshot') as saved:
            fixtures.measurement_operation(self.page, 'save')
        self.assertTrue(saved.value.ok, saved.value.text())
        self.now = 5
        fixtures.expect_counter_exposure(self.page, 5)
        windows = self.state()['counter_windows']
        self.assertEqual((len(windows['counter']), len(windows['counter_b'])), (5, 1))
        self.screenshot('beta-five-windows-one-window')
        before = self.state()['instruments']['counter_b']
        fixtures.measurement_operation(self.page, 'cache')
        expect(self.page.locator('#measurement-overwrite')).to_have_text('载入将覆盖当前测量数据')
        self.page.locator('#measurement-cancel').click()
        self.assertEqual(self.state()['instruments']['counter']['exposure_s'], 5)
        fixtures.measurement_operation(self.page, 'cache')
        self.page.locator('#measurement-confirm').click()
        fixtures.expect_counter_exposure(self.page, 3)
        self.assertEqual(self.state()['instruments']['counter_b'], before)
        self.start()
        self.now = 6
        fixtures.expect_counter_exposure(self.page, 4)
        self.assertEqual(len(self.state()['counter_windows']['counter']), 4)
        self.page.locator('[data-page=records]').click()
        with self.page.expect_download() as download:
            self.page.locator('#download-experiment').click()
        self.assertRegex(download.value.suggested_filename, r'^BABS_\d{8}-\d{6}-\d{6}\.nuclemu$')
        path = Path(self.folder.name, 'windows.nuclemu')
        download.value.save_as(path)
        doc = load_package(path)
        identity = next(item['id'] for item in doc['items'] if item['kind'] == 'measurement')
        for fmt in ('json', 'csv'):
            source = Path(self.folder.name, 'three-windows.' + fmt)
            source.write_bytes(export_item(doc, identity, fmt))
            self.page.locator('[data-page=instrument]').click()
            with self.page.expect_file_chooser() as chooser:
                fixtures.measurement_operation(self.page, 'file')
            chooser.value.set_files(source)
            expect(self.page.locator('#measurement-overwrite')).to_be_visible()
            self.page.locator('#measurement-confirm').click()
            fixtures.expect_counter_exposure(self.page, 3)
            self.assertEqual(len(self.state()['counter_windows']['counter']), 3)
            self.assertEqual(self.state()['instruments']['counter_b']['exposure_s'], 6)
