"""Historical aggregate counts remain visible without inventing old windows."""
from pathlib import Path
from copy import deepcopy
import os
import unittest
import test_catalog_records_browser as fixtures
from nuclemu.exchange import export_item, import_item, load_item, load_package, package_bytes
from test_measurement_provenance import old_document
from test_web_measurement_modes import current_document, independent_document
if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class CounterHistoryBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def retain(self, path, name):
        if output := os.environ.get('NUCLEMU_REVIEW_OUTPUT'):
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(path.read_bytes())

    def load_file(self, path):
        with self.page.expect_file_chooser() as choosing:
            self.page.get_by_role('button', name='从文件选择', exact=True).click()
        choosing.value.set_files(path)
        expect(self.page.locator('#measurement-load')).to_be_visible()

    def test_aggregate_prefix_zero_new_window_file_and_cache(self):
        source = old_document()
        item = source['items'][1]
        item['document'].pop('windows')
        path = Path(self.folder.name, 'old-aggregate.csv')
        path.write_bytes(export_item(source, item['id'], 'csv'))
        self.retain(path, 'historical-aggregate.csv')
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        self.load_file(path)
        notice = self.page.locator('#measurement-mode').inner_text()
        self.assertIn('版本与当前课程不同', notice)
        self.page.locator('#measurement-confirm').click()
        expect(self.page.locator('#measurement-load')).not_to_be_visible()
        panel = self.page.locator('.counter-window[data-device=counter_b]')
        expect(panel.locator('.counter-history')).to_have_text('含历史累计：296 次 / 3 s（无逐窗明细）')
        expect(panel.locator('.counter-total')).to_have_text('累计读数：296 次 / 3 s')
        expect(panel.locator('.window-reading strong')).to_have_text('—')
        expect(panel.locator('tbody')).to_contain_text('暂无逐窗读数')
        self.screenshot('historical-aggregate-loaded')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'start_group') as started:
            self.page.locator('#start').click()
        self.assertTrue(started.value.ok, started.value.text())
        self.now = 1
        expect(panel.locator('.window-reading strong')).to_have_text('0')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'stop_group') as stopped:
            self.page.locator('#stop').click()
        self.assertTrue(stopped.value.ok, stopped.value.text())
        expect(panel.locator('.counter-total')).to_have_text('累计读数：296 次 / 4 s')
        expect(panel.locator('.counter-history')).to_have_text('含历史累计：296 次 / 3 s（无逐窗明细）')
        expect(panel.locator('tbody tr')).to_have_count(1)
        self.assertEqual(panel.locator('tbody tr td').all_text_contents(), ['1', '1', '0'])
        current = self.state()['instruments']['counter_b']
        self.assertEqual((current['counts'], current['readable_exposure_s']), ([296], 4))
        self.screenshot('historical-prefix-plus-zero-window')
        # The same source imported into the receiving course must retain its notice.
        self.page.locator('[data-page=records]').click()
        with self.page.expect_file_chooser() as choosing:
            self.page.locator('#choose-import').click()
        choosing.value.set_files(path)
        expect(self.page.locator('#import-choice')).to_be_visible()
        self.page.locator('#confirm-import').click()
        expect(self.page.locator('#import-choice')).not_to_be_visible()
        self.page.locator('[data-page=instrument]').click()
        self.page.get_by_role('button', name='从本场实验记录选择', exact=True).click()
        expect(self.page.locator('#measurement-load')).to_be_visible()
        expect(self.page.locator('#measurement-mode')).to_have_text(notice)
        self.page.locator('#measurement-cancel').click()
        self.assertEqual(self.state()['instruments']['counter_b']['counts'], [296])
        # Real downloads preserve the original aggregate, without invented windows.
        self.page.locator('[data-page=records]').click()
        self.page.locator('#products .product input').check()
        with self.page.expect_download() as downloading:
            self.page.locator('#export').click()
        copy = Path(self.folder.name, downloading.value.suggested_filename)
        downloading.value.save_as(copy)
        self.retain(copy, 'historical-aggregate-roundtrip.csv')
        doc = load_item(copy.read_bytes())
        product = doc['items'][0]['document']
        self.assertEqual(product['snapshot']['exposure_s'], 3)
        self.assertEqual(sum(s['readings']['counter_b'][0] for s in product['segments']), 296)
        self.assertFalse(product.get('windows'))
        with self.page.expect_download() as downloading:
            self.page.locator('#download-experiment').click()
        whole = Path(self.folder.name, 'whole.nuclemu')
        downloading.value.save_as(whole)
        self.retain(whole, 'historical-aggregate-roundtrip.nuclemu')
        reopened = load_package(whole.read_bytes())
        self.assertEqual(len(reopened['items']), 1)
        self.assertEqual(reopened['items'][0]['document'], product)
        self.page.locator('[data-page=instrument]').click()
        self.load_file(copy)
        expect(self.page.locator('#measurement-mode')).to_have_text(notice)
        self.page.locator('#measurement-confirm').click()
        expect(self.page.locator('#measurement-load')).not_to_be_visible()
        expect(panel.locator('.counter-total')).to_have_text('累计读数：296 次 / 3 s')
        expect(panel.locator('.window-reading strong')).to_have_text('—')
        self.assertEqual(self.state()['counter_windows']['counter_b'], [])

    def test_record_selection_distinguishes_current_old_and_unknown_responses(self):
        doc = current_document()
        fresh = doc['items'][0]['id']
        old = independent_document()
        historical = import_item(doc, old, old['items'][0]['id'])
        unknown = current_document()
        foreign = deepcopy(old_document()['items'][1])
        foreign.pop('response_context', None)
        unknown['items'] = [foreign]
        unknown_id = import_item(doc, unknown, foreign['id'])
        path = Path(self.folder.name, 'mixed-responses.nuclemu')
        path.write_bytes(package_bytes(doc))
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        self.load_file(path)
        selector = self.page.locator('#measurement-choice')
        selector.select_option(fresh)
        expect(self.page.locator('#measurement-mode')).not_to_be_visible()

        selector.select_option(historical)
        expect(self.page.locator('#measurement-mode')).to_contain_text('版本与当前课程不同')
        expect(self.page.locator('#measurement-mode')).not_to_contain_text('来源响应不详')
        self.screenshot('selected-old-independent-response')
        selector.select_option(unknown_id)
        expect(self.page.locator('#measurement-mode')).to_contain_text('来源响应不详')
        expect(self.page.locator('#measurement-mode')).to_contain_text('当前课程的独立双窗响应')
        self.screenshot('selected-unknown-response')
        selector.select_option(fresh)
        expect(self.page.locator('#measurement-mode')).not_to_be_visible()

    def test_window_enter_then_start_applies_the_displayed_length(self):
        self.enter('beta')
        self.page.locator('#output-beta_detector').check()
        self.page.locator('[data-page=instrument]').click()
        received = []
        self.page.on('request', lambda request: received.append(request.post_data_json)
                     if request.url.endswith('/api/action') else None)
        field = self.page.locator('#window-size-counter_b')
        field.fill('10')
        field.press('Enter')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'start_group') as started:
            self.page.locator('#start').click()
        self.assertTrue(started.value.ok)
        self.assertEqual(self.state()['instruments']['counter_b']['window_s'], 10, received)
        self.now = 30
        expect(self.page.locator('.counter-window[data-device=counter_b] tbody tr')).to_have_count(3)
        self.assertEqual(self.state()['instruments']['counter_b']['window_s'], 10)



if __name__ == '__main__': unittest.main()
