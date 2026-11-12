"""Real alpha spectrum workflow: cumulative channels, ROI and energy calibration."""

import unittest

import test_catalog_records_browser as fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class SpectrumWorkspaceBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def set_part(self, part, values):
        self.page.locator('[data-page=setup]').click()
        self.page.locator(f'[data-part="{part}"]').click()
        changed = False
        for key, value in values.items():
            field = self.page.locator(f'#component [name="{key}"]')
            if field.evaluate('node => node.tagName') == 'SELECT':
                changed |= float(field.input_value()) != value
                field.select_option(str(value))
            else:
                changed |= float(field.input_value()) != value
                field.fill(str(value))
        if changed:
            with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                           r.request.post_data_json.get('action') == 'configure') as configured:
                self.page.locator('#component form button').click()
            self.assertTrue(configured.value.ok, configured.value.text())
        for key, value in values.items():
            self.assertEqual(self.state()['settings'][key], value)

    def alpha(self, source):
        self.enter('alpha')
        self.set_part('source', {'source_present': source})
        self.set_part('foil', {'foil_spec_um': 1, 'foil_count': 0})
        self.page.locator('[data-part=detector]').click()
        self.page.locator('#part-output').check()
        expect(self.page.locator('#part-output')).to_be_checked()
        self.page.locator('[data-part=mca]').click()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        self.page.locator('#open-instrument').click()
        expect(self.page.locator('#device')).to_have_value('mca')
        expect(self.page.locator('#other')).to_have_count(0)

    def analysis(self):
        if self.page.locator('#menu-analysis').get_attribute('aria-expanded') != 'true':
            self.page.locator('#menu-analysis').click()

    def roi(self, first, last):
        self.analysis()
        self.page.locator('#first').fill(str(first))
        self.page.locator('#last').fill(str(last))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'analysis') as selected:
            self.page.locator('#roi button').click()
        self.assertTrue(selected.value.ok, selected.value.text())
        expect(self.page.locator('#roi-result')).to_contain_text(f'ROI {first}–{last} 道')
        readout = self.state()['readout']
        expect(self.page.locator('#roi-result')).to_contain_text(f"选区计数 {readout['roi_counts']:,} 次")
        return readout

    def channels(self):
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#channel-table')).to_have_count(0)
        state = self.state()
        indices = [state['selected']] if state['selected'] is not None else [
            i for i, segment in enumerate(state['product']['segments'])
            if 'mca' in segment['readings'] and segment['acquisition'] == state['instrument']['acquisition']]
        exported = self.page.request.post(self.url + '/api/export', data=dict(
            session=state['id'], device='mca', format='json', kind='measurement', indices=indices))
        self.assertTrue(exported.ok, exported.text())
        segments = exported.json()['segments']
        self.assertTrue(all(len(segment['readings']['mca']) == 1024 for segment in segments))
        return [sum(segment['readings']['mca'][channel] for segment in segments) for channel in range(1024)]

    def test_alpha_three_peaks_roi_two_point_calibration_and_complete_export(self):
        self.alpha(1)
        fixtures.start_collection(self, 60)
        self.now = 60
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'false')
        state = self.state()
        total = state['readout']['counts']
        self.assertGreater(total, 3000)
        self.assertEqual(self.channels(), state['instrument']['counts'])
        self.assertEqual(sum(self.channels()), total)
        expect(self.page.locator('#spectrum-total')).to_contain_text('可读曝光 60 s')
        low = self.roi(845, 875)
        high = self.roi(952, 982)
        for peak in (low, high):
            self.assertGreater(peak['roi_counts'], 500)
        expect(self.page.locator('#roi-result')).to_contain_text('峰心 ')
        self.page.locator('details.calibration-tools > summary').click()
        expect(self.page.locator('#save-calibration')).to_be_disabled()
        expect(self.page.locator('#load-calibration')).to_be_visible()
        expect(self.page.locator('#cal-file')).not_to_be_visible()
        with self.page.expect_file_chooser() as chooser:
            self.page.locator('#load-calibration').click()
        chooser.value.set_files([])
        for name, value in (('c1', low['centroid']), ('e1', 5.155),
                            ('c2', high['centroid']), ('e2', 5.805)):
            self.page.locator(f'#calibrate [name={name}]').fill(str(value))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'calibrate') as calibrated:
            self.page.locator('#calibrate button').click()
        self.assertTrue(calibrated.value.ok, calibrated.value.text())
        applied = self.state()
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'cache_calibration') as cached:
            self.page.locator('#save-calibration').click()
        self.assertTrue(cached.value.ok, cached.value.text())
        expect(self.page.locator('#calibration-notice')).to_have_text('刻度已保存到本场记录')
        saved = self.state()
        self.assertEqual(len(saved['cached_calibrations']), 1)
        self.assertEqual(saved['calibration'], applied['calibration'])
        self.assertEqual(saved['instrument'], applied['instrument'])
        middle = self.roi(900, 928)
        self.assertGreater(middle['roi_counts'], 500)
        self.assertAlmostEqual(middle['energy_MeV'], 5.486, delta=.003)
        expect(self.page.locator('#roi-result')).to_contain_text('MeV')
        self.page.locator('#menu-display').click()
        canvas = self.page.locator('#plot').evaluate('node => node.toDataURL()')
        self.page.locator('#energy').check()
        self.page.wait_for_function("previous => document.querySelector('#plot').toDataURL() !== previous", arg=canvas)
        self.assertTrue(self.state()['analysis']['energy_axis'])
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'analysis'):
            self.page.locator('#energy').uncheck()
        self.assertFalse(self.state()['analysis']['energy_axis'])
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'analysis'):
            self.page.locator('#energy').check()
        self.page.keyboard.press('Escape')
        self.page.set_viewport_size({'width': 1366, 'height': 844})
        self.analysis()
        expect(self.page.locator('#roi-result')).to_be_visible()
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
        self.screenshot('alpha-spectrum-workspace-1366')
        self.page.keyboard.press('Escape')
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
        self.page.locator('#menu-display').click()
        self.page.locator('#spectrum-range').select_option('full')
        self.page.keyboard.press('Escape')
        self.screenshot('alpha-spectrum-full-range-1366')

    def test_waiting_zero_spectrum_cumulative_round_and_explicit_history(self):
        self.alpha(0)
        expect(self.page.locator('#channel-table')).to_have_count(0)
        expect(self.page.locator('#spectrum-total')).to_have_count(0)
        fixtures.start_collection(self, 1)
        self.now = 1
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'false')
        self.assertEqual(self.channels(), [0] * 1024)
        zero = self.roi(845, 875)
        self.assertEqual(zero['roi_counts'], 0)
        self.assertIsNone(zero['centroid'])
        expect(self.page.locator('#roi-result')).to_contain_text('峰心 无计数')
        self.set_part('source', {'source_present': 1})
        fixtures.start_collection(self, 2)
        self.now = 2
        expect(self.page.locator('#current-readout')).to_contain_text(' / 1 s')
        self.page.locator('#stop').click()
        expect(self.page.locator('#start')).to_be_enabled()
        acquisition = self.state()['instrument']['acquisition']
        self.set_part('source', {'source_present': 0})
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 3
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'false')
        state = self.state()
        self.assertEqual(state['instrument']['acquisition'], acquisition)
        self.assertGreater(state['readout']['counts'], 0)
        self.assertEqual(sum(self.channels()), state['readout']['counts'])
        segments = state['product']['segments']
        self.assertEqual(sum(segments[-1]['readings']['mca']), 0)
        self.page.locator('#menu-display').click()
        self.page.locator('#sample').select_option(str(len(segments) - 1))
        self.page.keyboard.press('Escape')
        self.assertEqual(self.channels(), [0] * 1024)
        self.page.locator('#menu-display').click()
        self.page.locator('#sample').select_option('')
        self.page.keyboard.press('Escape')
        self.assertEqual(sum(self.channels()), state['readout']['counts'])


if __name__ == '__main__':
    unittest.main()
