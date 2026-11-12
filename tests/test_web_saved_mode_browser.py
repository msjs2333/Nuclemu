"""Historical whole files and single measurements explain continuation mode."""

from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
import test_exchange_restore_definition as historical
from nuclemu.exchange import export_item, package_bytes

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class SavedModeBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def test_historical_whole_file_keeps_shared_continuation(self):
        doc = historical.BetaSavedModeTests().old_document()
        path = Path(self.folder.name, 'saved-beta.nuclemu')
        path.write_bytes(package_bytes(doc))
        self.page.locator('#open-package').set_input_files(path)
        expect(self.page.locator('#lab-title')).to_contain_text('历史共享输入')
        expect(self.page.locator('#portable-mode')).to_contain_text('继续测量沿用原共享输入模式')
        self.page.locator('[data-page=setup]').click()
        self.page.locator('#connections summary').click()
        expect(self.page.locator('#connections .markdown-body')).to_have_count(0)
        self.page.locator('[data-page=instrument]').click()
        fixtures.enable_output(self)
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'start_group'):
            self.page.locator('#start').click()
        self.now = 1
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(1)
        current = self.state()
        self.assertEqual(len(current['definition']['outputs']), 1)
        self.assertEqual(current['instruments']['counter']['counts'], current['instruments']['counter_b']['counts'])
        self.assertEqual(current['instruments']['counter']['exposure_s'], 1)
        self.screenshot('saved-whole-shared-mode')

    def test_old_single_measurement_explains_current_mode_before_and_after_load(self):
        doc = historical.BetaSavedModeTests().old_document()
        item = next(i for i in doc['items'] if i['document']['snapshot']['device'] == 'counter_b')
        path = Path(self.folder.name, 'saved-window.csv')
        path.write_bytes(export_item(doc, item['id'], 'csv'))
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#device').select_option('counter_b')
        with self.page.expect_file_chooser() as choosing:
            self.page.get_by_role('button', name='从文件选择', exact=True).click()
        choosing.value.set_files(path)
        expect(self.page.locator('#measurement-mode')).to_contain_text('原有读数保留')
        expect(self.page.locator('#measurement-mode')).to_contain_text('独立')
        self.page.locator('#measurement-confirm').click()
        expect(self.page.locator('#message')).to_contain_text('原有读数保留')
        expect(self.page.locator('#message')).to_contain_text('独立')
        current = self.state()
        self.assertEqual(current['instruments']['counter_b']['counts'], [296])
        self.assertEqual(current['instruments']['counter_b']['exposure_s'], 3)
        self.assertEqual(current['instruments']['counter']['exposure_s'], 0)
        self.assertEqual(len(current['definition']['outputs']), 2)
        self.screenshot('saved-single-current-mode')
