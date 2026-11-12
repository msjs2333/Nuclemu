"""The existing wiring disclosure renders the shared course overview source."""

from pathlib import Path
import unittest
import test_catalog_records_browser as fixtures
import test_exchange_restore_definition as historical

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class ApparatusOverviewBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def test_both_builtin_overviews_match_source_in_existing_disclosure(self):
        source = Path('docs/apparatus-overview.md').read_text(encoding='utf-8')
        for course, title in [('alpha', 'α 能量损失'), ('beta', 'β 吸收')]:
            with self.subTest(course=course):
                self.enter(course)
                box = self.page.locator('#connections')
                expect(box.locator('.markdown-body')).not_to_be_visible()
                box.locator('summary').click()
                section = source.split('## ' + title, 1)[1].split('\n## ', 1)[0].strip()
                expect(box.locator('.markdown-body p')).to_have_text(section.split('\n\n'))
                expect(box.locator('ul')).to_have_count(0)
                self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
                bounds = box.bounding_box()
                self.assertLessEqual(bounds['y'] + bounds['height'], 768)
                self.screenshot('apparatus-overview-' + course)
                self.page.locator('#menu-file').click()
                self.page.locator('#leave').click()
                self.page.locator('#discard').click()
                expect(self.page.locator('[data-experiment=' + course + ']')).to_be_visible()

    def test_external_course_keeps_connection_list(self):
        _, course = historical.profiles()
        self.server.app.definitions[course.id] = course
        self.page.reload()
        self.enter(course.id)
        box = self.page.locator('#connections')
        box.locator('summary').click()
        expect(box.locator('.markdown-body')).to_have_count(0)
        expect(box.locator('li')).to_have_count(2)
