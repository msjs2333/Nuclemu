"""Desktop student materials keep apparatus drafts and independent gates intact."""

from pathlib import Path
import re
import unittest

import test_catalog_records_browser as fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class StudentReaderBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def open_reader(self):
        self.page.locator('[data-page=materials]').click()
        expect(self.page.locator('#student-page')).to_be_visible()
        expect(self.page.locator('[data-page=materials]')).to_have_attribute('aria-current', 'page')
        expect(self.page.locator('.student-page-heading')).to_contain_text('β')
        body = self.page.locator('#student-page-body')
        expect(body).to_contain_text('简介与目的')
        expect(body).to_contain_text('器材与接线')
        text = body.inner_text()
        for forbidden in ('教师', 'golden', 'LINE_RATE_HZ', 'HALF_VALUE_AREAL_DENSITY_G_CM2'):
            self.assertNotIn(forbidden, text)
        expect(body.locator('table').first).to_be_visible()
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
        return body

    def test_catalogue_intro_uses_student_source_and_reader_keeps_unsent_foil_draft(self):
        for experiment in ('alpha', 'beta'):
            source = Path('docs', experiment + '.md').read_text(encoding='utf-8')
            intro = re.split(r'## (?:实验)?简介与目的', source, maxsplit=1)[1].split('\n## ', 1)[0].strip()
            intro = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', intro).replace('`', '').replace('*', '')
            card = self.page.locator('article').filter(has=self.page.locator(f'[data-experiment={experiment}]'))
            actual = card.locator('.course-intro').inner_text()
            self.assertEqual(' '.join(actual.split()), ' '.join(intro.split()))
            self.assertNotIn('教师', actual)
            self.assertNotIn('golden', actual)
        self.enter('beta')
        self.page.locator('#operation-tab').click()
        field = self.page.locator('#component [name=foil_count]')
        field.fill('2')
        self.assertEqual(self.state()['settings']['foil_count'], 0)
        body = self.open_reader()
        self.assertTrue(body.locator('.reader-table').evaluate_all(
            'tables => tables.some(table => table.scrollWidth > table.clientWidth)'))
        self.screenshot('student-reader-beta-desktop')
        self.page.locator('#student-page-back').click()
        expect(self.page.locator('#student-page')).not_to_be_visible()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        expect(field).to_have_value('2')
        self.assertEqual(self.state()['settings']['foil_count'], 0)

    def test_reader_return_keeps_running_counter_and_reports_actual_exposure(self):
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        fixtures.enable_output(self)
        self.page.locator('#start').click()
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'true')
        original = self.state()
        self.open_reader()
        self.now = 1
        expect(self.page.locator('#student-page-status')).to_contain_text('采集中')
        expect(self.page.locator('#student-page-status')).to_contain_text(re.compile(r'曝光\s*1\s*s'))
        reading = self.state()
        self.assertTrue(reading['running'])
        self.assertEqual(reading['instrument']['acquisition'], original['instrument']['acquisition'])
        self.assertEqual(reading['instrument']['exposure_s'], 1)
        self.screenshot('student-reader-beta-running-desktop')
        self.page.locator('#student-page-back').click()
        expect(self.page.locator('#student-page')).not_to_be_visible()
        expect(self.page.locator('[data-page=instrument]')).to_have_attribute('aria-current', 'page')
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'true')
        self.now = 2
        fixtures.expect_counter_exposure(self.page, 2)
        fixtures.expect_counter_exposure(self.page, 2, 'counter_b')
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(2)
        expect(self.page.locator('.counter-window[data-device=counter_b] tbody tr')).to_have_count(2)
        self.assertEqual(self.state()['instrument']['exposure_s'], 2)


if __name__ == '__main__':
    unittest.main()
