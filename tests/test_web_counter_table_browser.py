"""Counter tables annotate only unfinished rows and retain condition details."""

import unittest
import test_catalog_records_browser as fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class CounterTableBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def action(self, name, click):
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == name) as response:
            click()
        self.assertTrue(response.value.ok, response.value.text())

    def test_partial_pause_resume_and_changed_conditions_in_three_columns(self):
        self.enter('beta')
        fixtures.enable_output(self)
        self.page.locator('#window-size-counter_b').fill('5')
        self.action('window_config', lambda: self.page.locator('#window-size-counter_b').press('Tab'))
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 2.5
        self.page.locator('[data-page=setup]').click()
        self.page.locator('[name=foil_count]').fill('4')
        self.action('configure', lambda: self.page.get_by_role('button', name='应用参数').click())
        self.page.locator('[data-page=instrument]').click()
        a = self.page.locator('.counter-window[data-device=counter]')
        b = self.page.locator('.counter-window[data-device=counter_b]')
        for panel in (a, b):
            expect(panel.locator('th')).to_have_text(['窗号', '实际曝光 / s', '计数 / 次'])
            expect(panel.locator('.unfinished-window')).to_have_text('未满窗')
        expect(a.locator('tbody tr')).to_have_count(3)
        expect(b.locator('tbody tr')).to_have_count(1)
        self.action('stop_group', lambda: self.page.locator('#stop').click())
        expect(b.locator('.unfinished-window')).to_have_text('未满窗 · 已暂停')
        expect(b.locator('tbody tr td')).to_have_count(3)
        self.screenshot('counter-table-paused-partial')
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 5
        expect(a.locator('tbody tr')).to_have_count(5)
        expect(b.locator('.unfinished-window')).to_have_count(0)
        expect(a.locator('.unfinished-window')).to_have_count(0)
        expect(b.locator('tbody td:first-child details')).to_have_count(1)
        b.locator('summary').click()
        expect(b.locator('details')).to_contain_text('铝箔片数 4')
        self.assertTrue(b.locator('.window-ledger').evaluate('(el) => el.scrollWidth <= el.clientWidth'))
        expect(self.page.locator('#counter')).not_to_contain_text('已结清')
        self.screenshot('counter-table-complete-conditions')
