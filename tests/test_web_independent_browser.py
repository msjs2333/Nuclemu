"""Independent Web gates display only their own exposure and observations."""

import unittest

import test_catalog_records_browser as fixtures
from nuclemu.catalog import discover

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class IndependentWebBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    records = fixtures.CatalogRecordsBrowserTests.records

    def test_split_signal_gates_exposure_and_sparse_history(self):
        self.server.app.definitions = discover(['examples/courses'])
        self.page.reload()
        self.enter('split-signal')
        self.page.locator('#operation-tab').click()
        output = self.page.request.get(self.url + '/api/state').json()['definition']['outputs'][0]['id']
        self.page.locator('#output-' + output).check()
        self.page.locator('[data-part=device-a]').click()
        self.page.locator('#open-instrument').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1.25
        expect(self.page.locator('#exposure')).to_have_text('1.25 s')
        expect(self.page.get_by_label('计数窗 A', exact=True).locator('.window-reading output')).to_have_text('本窗实际曝光 1 s')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#snapshot-notice')).to_contain_text('已保存')
        self.page.locator('#device').select_option('b')
        expect(self.page.locator('#start')).to_be_enabled()
        expect(self.page.locator('#stop')).to_be_disabled()
        expect(self.page.locator('#exposure')).to_have_text('0 s')
        expect(self.page.get_by_label('计数窗 B', exact=True).locator('.window-reading output')).to_have_text('尚无结清窗')
        self.records()
        expect(self.page.locator('#products .product')).to_have_count(1)
        expect(self.page.locator('#products [data-device=a]')).to_have_count(1)
        expect(self.page.locator('#products [data-device=b]')).to_have_count(0)
        self.page.locator("[data-page='instrument']").click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1.75
        expect(self.page.locator('#exposure')).to_have_text('0.5 s')
        expect(self.page.get_by_label('计数窗 B', exact=True).locator('.window-reading output')).to_have_text('尚无结清窗')
        self.now = 2.5
        expect(self.page.locator('#exposure')).to_have_text('1.25 s')
        expect(self.page.get_by_role('region', name='窗 B 逐窗数据').locator('tbody tr')).to_have_count(1)
        expect(self.page.get_by_role('region', name='窗 B 逐窗数据').locator('tbody tr td').nth(1)).to_have_text('1')
        self.page.locator('#stop').click()
        expect(self.page.locator('#start')).to_be_enabled()
        expect(self.page.get_by_role('region', name='窗 B 逐窗数据').locator('tbody tr').last.locator('td').nth(1)).to_have_text('0.25')
        self.page.locator('#device').select_option('a')
        expect(self.page.locator('#stop')).to_be_enabled()
        expect(self.page.locator('#exposure')).to_have_text('2.5 s')
        a_rows = self.page.get_by_role('region', name='窗 A 逐窗数据').locator('tbody tr')
        expect(a_rows).to_have_count(3)
        expect(a_rows.last.locator('td').nth(1)).to_have_text('0.5')
        expect(a_rows.last.locator('td').last).to_contain_text('进行中')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#snapshot-notice')).to_contain_text('已保存')
        session = self.server.app.lab.work.session
        self.assertTrue(session.instrument('a').running)
        self.assertFalse(session.instrument('b').running)
        self.assertEqual([snapshot.exposure_s for snapshot in session.snapshots], [1, 2.5])
        self.assertEqual(self.server.app.catalog()['archives'], [])

    def test_legacy_shared_gate_course_still_reads_and_stops(self):
        self.enter('records-test')
        self.page.locator("[data-page='instrument']").click()
        expect(self.page.locator('#detector-output')).to_have_count(0)
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1.25
        self.page.locator('#device').select_option('right')
        expect(self.page.locator('#stop')).to_be_enabled()
        expect(self.page.locator('#counts tbody tr td').nth(1)).to_have_text('7')
        self.page.locator('#stop').click()
        expect(self.page.locator('#start')).to_be_enabled()
        self.assertFalse(self.server.app.lab.work.session.running)
        product = self.server.app.lab.work.product()
        self.assertEqual(set(product['segments'][0]['readings']), {'left', 'right'})


if __name__ == '__main__':
    unittest.main()
