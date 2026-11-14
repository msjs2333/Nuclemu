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
        self.page.locator('#operation-tab').click()
        if self.state()['settings']['source_present'] == value:
            return
        self.page.locator('[name=source_present]').select_option(str(value))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'configure') as applied:
            self.page.locator('#component form button').click()
        self.assertTrue(applied.value.ok)

    def detector(self):
        self.page.locator("[data-page='setup']").click()
        self.page.locator('[data-part=detector]').click()
        expect(self.page.locator('#setup')).to_be_visible()
        expect(self.page.locator('#open-instrument')).to_have_count(0)
        self.page.locator('#operation-tab').click()
        output = self.state()['definition']['outputs'][0]['id']
        self.page.locator('#output-' + output).check()

    def open_instrument(self, component):
        self.page.locator("[data-page='setup']").click()
        self.page.locator(f'[data-part={component}]').click()
        expect(self.page.locator('#setup')).to_be_visible()
        self.page.locator('#open-instrument').click()
        expect(self.page.locator('#instrument')).to_be_visible()

    def screenshot_sizes(self, name):
        for width, suffix in ((1366, 'desktop'),):
            self.page.set_viewport_size({'width': width, 'height': 844})
            self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
            self.screenshot(name + '-' + suffix)
        self.page.set_viewport_size({'width': 1366, 'height': 844})

    def test_beta_single_counter_has_two_bound_windows_and_group_controls(self):
        self.enter('beta')
        expect(self.page.locator('[data-part=counter]')).to_have_count(1)
        expect(self.page.locator('[data-part=counter_b]')).to_have_count(0)
        self.source(1)
        self.detector()
        self.open_instrument('counter')
        expect(self.page.locator('.counter-window')).to_have_count(2)
        first, second = [self.page.get_by_role('region', name=f'窗 {name} 逐窗数据') for name in ('A', 'B')]
        panels = self.page.locator('.counter-window')
        left, right = [panels.nth(i).bounding_box() for i in range(2)]
        self.assertAlmostEqual(left['y'], right['y'], delta=1)
        self.assertAlmostEqual(left['width'], right['width'], delta=1)
        self.assertLess(left['x'] + left['width'], right['x'])
        for device, window in (('counter', '2'), ('counter_b', '5'), ('counter', '1')):
            field = self.page.locator('#window-size-' + device)
            field.fill(window)
            with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'window_config') as configured:
                field.press('Tab')
            self.assertTrue(configured.value.ok)
            self.assertEqual(configured.value.request.post_data_json['device'], device)
            self.assertEqual(configured.value.request.post_data_json['window_s'], float(window))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'start_group') as started:
            self.page.locator('#start').click()
        self.assertEqual(started.value.request.post_data_json['component'], 'counter')
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 5
        expect(first.locator('tbody tr')).to_have_count(5)
        expect(second.locator('tbody tr')).to_have_count(1)
        expect(self.page.locator('#device')).to_have_count(0)
        expect(self.page.locator('#stop')).to_be_enabled()
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'stop_group') as stopped:
            self.page.locator('#stop').click()
        self.assertEqual(stopped.value.request.post_data_json['component'], 'counter')
        expect(self.page.get_by_role('region', name='窗 A', exact=True).locator('.window-state')).to_have_text('暂停')
        expect(self.page.get_by_role('region', name='窗 B', exact=True).locator('.window-state')).to_have_text('暂停')
        self.assertFalse(self.server.app.lab.work.session.instrument('counter').running)
        self.assertFalse(self.server.app.lab.work.session.instrument('counter_b').running)
        self.screenshot('beta-single-counter-two-windows-desktop')

    def test_beta_background_cache_clear_source_and_sample(self):
        self.enter('beta')
        expect(self.page.locator('#apparatus [aria-pressed=true]')).to_have_count(0)
        # New experiments start with an empty source holder.
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
        fixtures.expect_counter_exposure(self.page, 3)
        fixtures.measurement_operation(self.page, 'save')
        expect(self.page.locator('#snapshot-notice')).not_to_be_visible()
        background = self.server.app.lab.work.session.snapshots[0]
        self.assertTrue(self.state()['running'])
        fixtures.measurement_operation(self.page, 'clear')
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.page.locator('#clear-discard').click()
        expect(self.page.locator('#clear-confirm')).not_to_be_visible()
        fixtures.expect_counter_exposure(self.page, 0)
        self.source(1)
        self.open_instrument('counter')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'start_group') as resumed:
            self.page.locator('#start').click()
        self.assertTrue(resumed.value.ok, resumed.value.text())
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 8
        fixtures.expect_counter_exposure(self.page, 5)
        fixtures.measurement_operation(self.page, 'save')
        expect(self.page.locator('#snapshot-notice')).not_to_be_visible()
        expect(self.page.locator('#background, #net-results')).to_have_count(0)
        sample = next(snapshot for snapshot in self.server.app.lab.work.session.snapshots
                      if snapshot.device == background.device and snapshot.id != background.id)
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
        from nuclemu.catalog import discover
        self.server.app.definitions = discover(['examples/courses'])
        self.page.reload()
        self.enter('split-signal')
        output = self.state()['definition']['outputs'][0]['id']
        self.page.locator('#output-' + output).check()
        self.open_instrument('device-a')
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('10')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.page.locator('#device').select_option('b')
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.page.locator('#device').select_option('a')
        self.now = 3
        expect(self.page.locator('#exposure')).to_have_text('3 s')
        fixtures.measurement_operation(self.page, 'clear')
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.page.reload()
        expect(self.page.locator('#clear-confirm')).to_be_visible()
        self.now = 5
        self.assertEqual(self.state()['time_s'], 5)
        session = self.server.app.lab.work.session
        self.assertEqual(session.instrument('a').exposure_s, 3)
        self.assertEqual(session.instrument('b').exposure_s, 5)
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
        a, b = session.instrument('a'), session.instrument('b')
        self.assertTrue(b.running)
        self.assertEqual(b.exposure_s, 7 if button == 'save' else 5)
        if choice in ('cancel', 'failure'):
            self.assertTrue(state['running'])
            self.assertEqual((a.exposure_s, a.remaining_s), (3, 7))
            self.now = state['time_s'] + 1
            self.state()
            a, b = session.instrument('a'), session.instrument('b')
            self.assertEqual((a.exposure_s, a.remaining_s), (4, 6))
            self.assertEqual(b.exposure_s, self.now)
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
        expect(self.page.locator('#exposure')).to_have_text('1 s')
        self.assertEqual(sum(self.state()['instrument']['counts']), 0)
        fixtures.measurement_operation(self.page, 'save')
        expect(self.page.locator('#snapshot-notice')).not_to_be_visible()
        self.screenshot_sizes('alpha-mca')


if __name__ == '__main__':
    unittest.main()
