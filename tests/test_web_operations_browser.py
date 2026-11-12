"""Student-visible apparatus controls, cached measurements and clear choices."""

import json
import os
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class WebOperationsBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def source(self, value):
        self.page.locator("[data-page='setup']").click()
        self.page.locator('[data-part=source]').click()
        self.page.locator('[name=source_present]').select_option(str(value))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'configure') as applied:
            self.page.locator('#component form button').click()
        self.assertTrue(applied.value.ok)

    def detector(self):
        self.page.locator("[data-page='setup']").click()
        self.page.locator('[data-part=detector]').click()
        expect(self.page.locator('#setup')).to_be_visible()
        expect(self.page.locator('#open-instrument')).to_have_count(0)
        self.page.locator('#part-output').check()

    def open_instrument(self, component):
        self.page.locator("[data-page='setup']").click()
        self.page.locator(f'[data-part={component}]').click()
        expect(self.page.locator('#setup')).to_be_visible()
        self.page.locator('#open-instrument').click()
        expect(self.page.locator('#device')).to_be_focused()

    def screenshot_sizes(self, name):
        for width, suffix in ((1366, 'desktop'),):
            self.page.set_viewport_size({'width': width, 'height': 844})
            self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
            self.screenshot(name + '-' + suffix)
        self.page.set_viewport_size({'width': 1366, 'height': 844})

    def test_beta_stacked_counters_are_separate_clickable_instruments(self):
        self.enter('beta')
        expect(self.page.locator('#apparatus')).to_have_class('apparatus dual-readouts')
        first = self.page.locator('[data-part=counter]').bounding_box()
        second = self.page.locator('[data-part=counter_b]').bounding_box()
        self.assertAlmostEqual(first['x'], second['x'], delta=1)
        self.assertLess(first['y'] + first['height'], second['y'])
        for component in ('counter', 'counter_b'):
            self.page.locator("[data-page='setup']").click()
            self.page.locator(f'[data-part={component}]').click()
            expect(self.page.locator('#setup')).to_be_visible()
            expect(self.page.locator(f'[data-part={component}]')).to_have_attribute('aria-pressed', 'true')
            with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'device') as selected:
                self.page.locator('#open-instrument').click()
            self.assertEqual(selected.value.request.post_data_json['device'], component)
            expect(self.page.locator('#device')).to_have_value(component)
        self.page.locator("[data-page='setup']").click()
        self.screenshot('beta-apparatus-stacked-desktop')
        self.source(0)
        self.screenshot('beta-apparatus-stacked-empty-desktop')

    def test_beta_background_cache_clear_source_and_sample(self):
        self.enter('beta')
        expect(self.page.locator('#apparatus [aria-pressed=true]')).to_have_count(0)
        self.source(0)
        expect(self.page.locator('[data-part=source] img')).to_have_attribute('src', '/rig-source-empty.webp')
        expect(self.page.locator('[data-part=foil] img')).to_have_attribute('src', '/rig-foil-empty.webp')
        self.detector()
        self.screenshot_sizes('beta-apparatus')
        self.open_instrument('counter')
        expect(self.page.locator('#detector-output')).to_have_count(0)
        expect(self.page.locator('#mode')).to_have_value('manual')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 3
        expect(self.page.locator('#exposure')).to_have_text('实际曝光 3 s')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#cache-count')).to_have_text('本场已保存 1 份')
        background = self.server.app.lab.work.session.snapshots[0]
        self.assertTrue(self.state()['running'])
        self.page.locator('#clear').click()
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.page.locator('#clear-discard').click()
        expect(self.page.locator('#clear-confirm')).not_to_be_visible()
        expect(self.page.locator('#exposure')).to_have_text('实际曝光 0 s')
        self.source(1)
        self.open_instrument('counter')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 8
        expect(self.page.locator('#exposure')).to_have_text('实际曝光 5 s')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#cache-count')).to_have_text('本场已保存 2 份')
        self.page.locator('#background').select_option('0')
        expect(self.page.locator('#net-results tr').nth(1).locator('td').last).to_contain_text(' ± ')
        sample = self.server.app.lab.work.session.snapshots[1]
        self.assertEqual((background.exposure_s, sample.exposure_s), (3, 5))
        self.assertEqual(self.server.app.lab.work.session.snapshots[0], background)
        self.screenshot_sizes('beta-counter')
        output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
        if output:
            evidence = dict(background=dict(counts=sum(background.counts), exposure_s=3),
                sample=dict(counts=sum(sample.counts), exposure_s=5),
                readout=self.state()['readout'], snapshots=self.state()['snapshots'])
            Path(output, 'beta-readings.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')

    def clear_case(self, choice):
        self.enter('beta')
        self.detector()
        self.open_instrument('counter')
        self.page.locator('#menu-acquisition').click()
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('10')
        self.page.keyboard.press('Escape')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.page.locator('#device').select_option('counter_b')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.page.locator('#device').select_option('counter')
        self.now = 3
        expect(self.page.locator('#exposure')).to_have_text('实际曝光 3 s')
        self.page.locator('#clear').click()
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.now = 5
        self.assertEqual(self.state()['time_s'], 5)
        session = self.server.app.lab.work.session
        self.assertEqual(session.instrument('counter').exposure_s, 3)
        self.assertEqual(session.instrument('counter_b').exposure_s, 5)
        def writer(item):
            self.assertEqual(item.exposure_s, 3)
            self.now = 7
            if choice == 'failure':
                raise OSError('controlled cache failure')
        self.server.app.lab.cache_writer = writer
        button = 'save' if choice == 'failure' else choice
        self.page.locator('#clear-' + button).click()
        expect(self.page.locator('#clear-confirm')).not_to_be_visible()
        if choice == 'failure':
            expect(self.page.locator('#error')).to_contain_text('controlled cache failure')
        state = self.state()
        a, b = session.instrument('counter'), session.instrument('counter_b')
        self.assertTrue(b.running)
        self.assertEqual(b.exposure_s, 7 if button == 'save' else 5)
        if choice in ('cancel', 'failure'):
            self.assertTrue(state['running'])
            self.assertEqual((a.exposure_s, a.remaining_s), (3, 7))
        else:
            self.assertFalse(state['running'])
            self.assertEqual(a.exposure_s, 0)
        self.assertEqual(len(session.snapshots), 1 if choice == 'save' else 0)

    def test_clear_yes(self): self.clear_case('save')
    def test_clear_no(self): self.clear_case('discard')
    def test_clear_cancel(self): self.clear_case('cancel')
    def test_clear_cache_failure(self): self.clear_case('failure')

    def test_alpha_apparatus_empty_source_and_closed_detector_are_distinct(self):
        self.enter('alpha')
        self.source(0)
        self.detector()
        self.screenshot_sizes('alpha-apparatus')
        self.open_instrument('mca')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1
        expect(self.page.locator('#exposure')).to_have_text('实际曝光 1 s')
        self.assertEqual(sum(self.state()['instrument']['counts']), 0)
        self.page.locator('#save-current').click()
        expect(self.page.locator('#cache-count')).to_have_text('本场已保存 1 份')
        self.screenshot_sizes('alpha-mca')


if __name__ == '__main__':
    unittest.main()
