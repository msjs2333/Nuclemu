"""Desktop student materials keep apparatus drafts and independent gates intact."""

from pathlib import Path
import json
import os
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
        expect(self.page.locator('.student-page-heading')).to_contain_text('实验资料')
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
        chapters = self.page.locator('.student-page-contents button')
        expect(chapters.first).to_have_attribute('aria-current', 'location')
        chapters.nth(2).click()
        expect(chapters.nth(2)).to_have_attribute('aria-current', 'location')
        self.page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
        expect(chapters.last).to_have_attribute('aria-current', 'location')
        self.page.evaluate('window.scrollTo(0, 0)')
        expect(chapters.first).to_have_attribute('aria-current', 'location')
        self.assertTrue(body.locator('.reader-table').evaluate_all(
            'tables => tables.every(table => table.clientWidth > 0 && '
            '(table.scrollWidth <= table.clientWidth || getComputedStyle(table).overflowX === "auto"))'))
        expect(self.page.locator('#student-page-status')).to_have_count(0)
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
        expect(self.page.locator('#stop')).to_be_enabled()
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
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 2
        fixtures.expect_counter_exposure(self.page, 2)
        fixtures.expect_counter_exposure(self.page, 2, 'counter_b')
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(2)
        expect(self.page.locator('.counter-window[data-device=counter_b] tbody tr')).to_have_count(2)
        self.assertEqual(self.state()['instrument']['exposure_s'], 2)

    def test_long_text_uses_the_full_reading_column_at_desktop_widths(self):
        self.enter('beta')
        self.open_reader()
        body = self.page.locator('#student-page-body')
        evidence = []
        for width in (1366, 1920):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for document in ('beta', 'gui', 'alpha'):
                if document == 'gui':
                    body.get_by_role('button', name='图形实验台', exact=True).click()
                elif document == 'alpha':
                    body.get_by_role('button', name='α学生章', exact=True).click()
                paragraph = body.locator('p').evaluate_all('''nodes => {
                    const p = [...nodes].sort((a,b) => b.textContent.length-a.textContent.length)[0];
                    p.scrollIntoView({block:'center'});
                    const column = document.querySelector('#student-page-body').getBoundingClientRect();
                    const box = p.getBoundingClientRect();
                    const range = document.createRange(); range.selectNodeContents(p);
                    const rects = [...range.getClientRects()];
                    return {columnWidth:column.width, paragraphWidth:box.width,
                        rightGap:column.right-Math.max(...rects.map(r=>r.right)),
                        lines:new Set(rects.map(r=>Math.round(r.top))).size,
                        pageWidth:document.documentElement.scrollWidth,
                        blockWidths:[...document.querySelectorAll('#student-page-body :is(h2,h3,p,ul,ol)')]
                            .map(n=>n.getBoundingClientRect().width)};
                }''')
                self.assertAlmostEqual(paragraph['paragraphWidth'], paragraph['columnWidth'], delta=1)
                self.assertGreater(paragraph['lines'], 1)
                self.assertLess(paragraph['rightGap'], 30)
                self.assertEqual(paragraph['pageWidth'], width)
                for block_width in paragraph['blockWidths']:
                    self.assertAlmostEqual(block_width, paragraph['columnWidth'], delta=1)
                expect(self.page.locator('.student-page-contents')).to_be_visible()
                expect(self.page.locator('#student-page-back')).to_be_in_viewport()
                evidence.append({'document':document, 'viewport':width, **paragraph})
                output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
                if output:
                    directory = Path(output)
                    directory.mkdir(parents=True, exist_ok=True)
                    self.page.screenshot(path=directory / f'reader-full-width-{document}-{width}.png')
            self.page.locator('#reader-back-to-lesson').click()
        output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
        if output:
            Path(output, 'reader-text-widths.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
