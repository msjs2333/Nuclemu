"""Apparatus help is an independent layer using the shared course overview."""

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

    def test_builtin_overviews_open_independently_and_return_to_selection(self):
        source = Path('docs/apparatus-overview.md').read_text(encoding='utf-8')
        for course, title in [('alpha', 'α 能量损失'), ('beta', 'β 吸收')]:
            with self.subTest(course=course):
                self.enter(course)
                self.page.locator('[data-part=detector]').click()
                expect(self.page.locator('[data-part=detector]')).to_have_attribute('aria-pressed', 'true')
                box = self.page.locator('#connections')
                expect(box.locator('.markdown-body')).not_to_be_visible()
                self.page.locator('#show-connections').click()
                expect(box).to_be_visible()
                section = source.split('## ' + title, 1)[1].split('\n## ', 1)[0].strip()
                expect(box.locator('.markdown-body p')).to_have_text(section.split('\n\n'))
                expect(box.locator('ul')).to_have_count(0)
                self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
                bounds = box.bounding_box()
                self.assertLessEqual(bounds['y'] + bounds['height'], 768)
                self.screenshot('apparatus-overview-' + course)
                self.page.keyboard.press('Escape')
                expect(box).not_to_be_visible()
                expect(self.page.locator('#show-connections')).to_be_focused()
                expect(self.page.locator('[data-part=detector]')).to_have_attribute('aria-pressed', 'true')
                expect(self.page.locator('#introduction-tab')).to_have_attribute('aria-selected', 'true')
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
        self.page.locator('#show-connections').click()
        expect(box.locator('.markdown-body')).to_have_count(0)
        expect(box.locator('li')).to_have_count(2)
