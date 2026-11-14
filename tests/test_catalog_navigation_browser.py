"""Desktop catalogue slots and the public student document navigation."""

from dataclasses import replace
import unittest

from nuclemu.catalog import discover
import test_catalog_records_browser as fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class CatalogNavigationBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def test_two_and_twelve_courses_keep_four_slots_and_keyboard_entry(self):
        self.server.app.definitions = discover()
        self.page.reload()
        cards = self.page.locator('.course')
        expect(cards).to_have_count(2)
        widths = cards.evaluate_all('nodes => nodes.map(n => n.getBoundingClientRect().width)')
        self.assertAlmostEqual(widths[0], widths[1], delta=1)
        self.assertLess(widths[0], 330)
        expect(self.page.locator('.github-link')).to_have_attribute('href', 'https://github.com/msjs2333/Nuclemu')
        expect(self.page.locator('#catalog-load')).to_have_text('从文件加载实验')
        heading = self.page.locator('#catalog .heading h1').bounding_box()
        load = self.page.locator('#catalog-load').bounding_box()
        self.assertLess(abs(heading['y'] + heading['height']/2 - load['y'] - load['height']/2), 3)
        for card in cards.all():
            expect(card.get_by_role('button')).to_have_count(1)
            button = card.get_by_role('button').bounding_box()
            box = card.bounding_box()
            self.assertAlmostEqual(button['width'], box['width'] - 2, delta=1)
            self.assertAlmostEqual(button['y'] + button['height'], box['y'] + box['height'] - 1, delta=1)
            self.assertTrue(card.locator('img').evaluate('(n) => n.complete && n.naturalWidth === 960'))
        self.screenshot('catalog-two-1366')
        definition = self.server.app.definitions['alpha']
        self.server.app.definitions = {
            f'course-{i:02}': replace(definition, id=f'course-{i:02}',
                title=f'第{i+1}项：核物理测量与统计涨落的长课程标题',
                description='考察测量条件与读数的关系，记录观测并比较结果。',
                course='课程布局样例') for i in range(12)}
        self.page.reload()
        expect(cards).to_have_count(12)
        boxes = cards.evaluate_all('nodes => nodes.map(n => {const r=n.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width}})')
        self.assertEqual(len(set(round(b['x']) for b in boxes)), 4)
        self.assertEqual(len(set(round(b['y']) for b in boxes)), 3)
        for box in boxes:
            self.assertAlmostEqual(box['width'], widths[0], delta=1)
        for card in cards.all():
            box = card.bounding_box()
            button = card.get_by_role('button').bounding_box()
            self.assertAlmostEqual(button['width'], box['width'] - 2, delta=1)
            self.assertAlmostEqual(button['y'] + button['height'], box['y'] + box['height'] - 1, delta=1)
        buttons = self.page.locator('[data-experiment]')
        buttons.first.focus()
        for i in range(12):
            expect(buttons.nth(i)).to_be_focused()
            if i < 11:
                self.page.keyboard.press('Tab')
        self.screenshot('catalog-twelve-1366')
        self.page.set_viewport_size({'width':1093, 'height':614})
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1093)
        self.screenshot('catalog-twelve-reduced-css-viewport')
        buttons.nth(11).press('Enter')
        expect(self.page.locator('#workspace')).to_be_visible()

    def test_external_material_and_three_public_documents(self):
        original = self.server.app.definitions['records-test']
        self.server.app.definitions['records-test'] = replace(original,
            description='外部课程简介保留。', guide=('## 课程操作', '外部课程操作内容保留。',
                '![装置示意](/cover-alpha-energy-loss.webp)', '[图形操作](gui.md)'))
        self.page.reload()
        self.enter('records-test')
        self.page.locator('[data-page=materials]').click()
        body = self.page.locator('#student-page-body')
        expect(body).to_contain_text('外部课程简介保留。')
        expect(body).to_contain_text('外部课程操作内容保留。')
        self.assertTrue(body.locator('img').evaluate('n => n.complete && n.naturalWidth === 960'))
        body.get_by_role('button', name='图形操作', exact=True).click()
        expect(body).to_contain_text('选择课程与装置')
        self.assertNotIn('界面维护', body.inner_text())
        links = body.locator('.reader-document-link')
        expect(links).to_have_count(2)
        links.first.click()
        expect(body).to_contain_text('实验简介与目的')
        expect(self.page.locator('#student-page-title')).to_contain_text('α')
        self.page.locator('#reader-back-to-lesson').click()
        expect(body).to_contain_text('外部课程操作内容保留。')
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
        self.screenshot('external-student-materials-desktop')
        self.page.locator('#student-page-back').click()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')


if __name__ == '__main__':
    unittest.main()
