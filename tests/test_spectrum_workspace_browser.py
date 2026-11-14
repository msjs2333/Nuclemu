"""Real alpha spectrum workflow: cumulative channels, ROI and energy calibration."""

import json
import re
from pathlib import Path
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
        self.page.locator('#operation-tab').click()
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
        self.page.locator('#output-alpha_detector').check()
        expect(self.page.locator('#output-alpha_detector')).to_be_checked()
        self.page.locator('[data-part=detector]').click()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        self.page.locator('[data-part=mca]').click()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        self.page.locator('#open-instrument').click()
        expect(self.page.locator('#device')).to_have_count(0)
        expect(self.page.locator('[data-page=instrument]')).to_have_text('多道谱仪')
        expect(self.page.locator('#other')).to_have_count(0)

    def analysis(self):
        self.page.get_by_role('tab', name='谱分析', exact=True).click()

    def start_collection(self, seconds):
        self.page.locator('[data-page=instrument]').click()
        self.page.get_by_role('tab', name='采集', exact=True).click()
        fixtures.start_collection(self, seconds)

    def roi(self, first, last):
        self.analysis()
        self.page.locator('#first').fill(str(first))
        self.page.locator('#last').fill(str(last))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'calculate_roi') as selected:
            self.page.locator('#roi button').click()
        self.assertTrue(selected.value.ok, selected.value.text())
        expect(self.page.locator('#roi-result')).to_contain_text(f'ROI {first}–{last} 道')
        readout = self.state()['roi_result']['readout']
        expect(self.page.locator('#roi-result')).to_contain_text(f"选区计数 {readout['roi_counts']:,} 次")
        return readout

    def save_current(self):
        self.page.get_by_role('tab', name='采集', exact=True).click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'commit_snapshot_group') as saved:
            fixtures.measurement_operation(self.page, 'save')
        self.assertTrue(saved.value.ok, saved.value.text())
        return saved.value.json()['snapshots'][-1]['id']

    def channels(self, snapshot_id=None):
        """Download an explicitly saved spectrum through the student record UI."""
        expect(self.page.locator('#channel-table')).to_have_count(0)
        if snapshot_id is None:
            snapshot_id = self.save_current()
        self.page.locator('[data-page=records]').click()
        for checkbox in self.page.locator('#products input:checked').all():
            checkbox.uncheck()
        identity = next(row['item_id'] for row in self.state()['snapshots'] if row['id'] == snapshot_id)
        row = self.page.locator(f'[data-key="r/{identity}"]')
        row.locator('select').select_option('json')
        row.locator('input').check()
        with self.page.expect_download() as pending:
            self.page.locator('#export').click()
        destination = Path(self.folder.name, f'spectrum-{snapshot_id}.json')
        pending.value.save_as(destination)
        exported = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(exported['format'], 'nuclemu.item/1')
        measurement = next(item for item in exported['items'] if item['kind'] == 'measurement')
        self.assertEqual(measurement['document']['snapshot']['id'], snapshot_id)
        segments = measurement['document']['segments']
        self.assertTrue(all(len(segment['readings']['mca']) == 1024 for segment in segments))
        self.page.locator('[data-page=instrument]').click()
        return [sum(segment['readings']['mca'][channel] for segment in segments) for channel in range(1024)]

    def test_alpha_three_peaks_roi_two_point_calibration_and_complete_export(self):
        self.alpha(1)
        self.start_collection(60)
        self.now = 60
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'false')
        state = self.state()
        total = state['readout']['counts']
        self.assertGreater(total, 3000)
        self.assertEqual(self.channels(), state['instrument']['counts'])
        self.assertEqual(sum(self.channels()), total)
        expect(self.page.locator('#spectrum-total, #peak')).to_have_count(0)
        expect(self.page.locator('#exposure')).to_have_text('60 s')
        low = self.roi(845, 875)
        high = self.roi(952, 982)
        for peak in (low, high):
            self.assertGreater(peak['roi_counts'], 500)
        expect(self.page.locator('#roi-result')).to_contain_text('重心 ')
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
        self.page.locator('#save-calibration').click()
        expect(self.page.locator('#calibration-name')).to_have_value(re.compile(r'^AEL_\d{8}-\d{6}_calibration$'))
        self.page.locator('#calibration-save-cancel').click()
        self.assertEqual(self.state()['cached_calibrations'], [])
        self.assertEqual(self.state()['calibration'], applied['calibration'])
        self.page.locator('#save-calibration').click()
        self.page.locator('#calibration-name').fill('两点能量刻度')
        self.screenshot('alpha-calibration-naming-dialog')
        def fail_calibration_save(route):
            if route.request.post_data_json.get('action') == 'cache_calibration':
                route.fulfill(status=500, json={'error': 'controlled calibration save failure'})
            else:
                route.continue_()
        self.page.route('**/api/action', fail_calibration_save)
        self.page.locator('#calibration-save-confirm').click()
        expect(self.page.locator('#calibration-save-error')).to_contain_text('controlled calibration save failure')
        expect(self.page.locator('#calibration-name')).to_have_value('两点能量刻度')
        self.assertEqual(self.state()['cached_calibrations'], [])
        self.page.unroute('**/api/action', fail_calibration_save)
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'cache_calibration') as cached:
            self.page.locator('#calibration-save-confirm').click()
        self.assertTrue(cached.value.ok, cached.value.text())
        expect(self.page.locator('#calibration-notice')).to_have_text('刻度已保存到本场记录')
        saved = self.state()
        self.assertEqual(len(saved['cached_calibrations']), 1)
        self.assertEqual(saved['cached_calibrations'][0]['title'], '两点能量刻度')
        self.assertEqual(saved['calibration'], applied['calibration'])
        self.assertEqual(saved['instrument'], applied['instrument'])
        middle = self.roi(900, 928)
        self.assertGreater(middle['roi_counts'], 500)
        self.assertAlmostEqual(middle['energy_MeV'], 5.486, delta=.003)
        expect(self.page.locator('#roi-result')).to_contain_text('MeV')
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
        self.page.set_viewport_size({'width': 1366, 'height': 844})
        self.analysis()
        expect(self.page.locator('#roi-result')).to_be_visible()
        expect(self.page.locator('#stop')).to_be_in_viewport(ratio=1)
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1366)
        self.screenshot('alpha-spectrum-workspace-1366')
        expect(self.page.locator('#menu-analysis, #menu-display, #spectrum-range')).to_have_count(0)
        self.assertEqual(sum(self.channels()), total)
        self.screenshot('alpha-spectrum-complete-export-1366')

    def test_waiting_zero_spectrum_cumulative_round_and_explicit_history(self):
        self.alpha(0)
        expect(self.page.locator('#channel-table')).to_have_count(0)
        expect(self.page.locator('#spectrum-total')).to_have_count(0)
        self.start_collection(1)
        self.now = 1
        expect(self.page.locator('#gate-status')).to_have_attribute('data-running', 'false')
        zero_snapshot = self.save_current()
        self.assertEqual(self.channels(zero_snapshot), [0] * 1024)
        zero = self.roi(845, 875)
        self.assertEqual(zero['roi_counts'], 0)
        self.assertIsNone(zero['centroid'])
        expect(self.page.locator('#roi-result')).to_contain_text('重心 无计数')
        self.set_part('source', {'source_present': 1})
        self.start_collection(2)
        self.now = 2
        expect(self.page.locator('#exposure')).to_have_text('1 s')
        self.assertEqual(self.state()['instrument']['readable_exposure_s'], 1)
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
        self.analysis()
        identity = next(snapshot['item_id'] for snapshot in self.state()['snapshots'] if snapshot['id'] == zero_snapshot)
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'select') as selected_response:
            self.page.locator('#sample').select_option(identity)
        self.assertTrue(selected_response.value.ok, selected_response.value.text())
        expect(self.page.locator('#sample')).to_have_value(identity)
        title = next(item['title'] for item in self.state()['saved_measurements'] if item['id'] == identity)
        expect(self.page.locator('#legend')).to_contain_text('当前谱：' + title)
        selected = self.state()
        self.assertEqual(selected['readout']['counts'], 0)
        self.assertEqual(selected['readout']['exposure_s'], 1)
        self.assertEqual(self.channels(zero_snapshot), [0] * 1024)
        self.analysis()
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'select') as current_response:
            self.page.locator('#sample').select_option('')
        self.assertTrue(current_response.value.ok, current_response.value.text())
        expect(self.page.locator('#sample')).to_have_value('')
        expect(self.page.locator('#legend')).to_contain_text('当前谱：本轮累计谱')
        self.assertEqual(sum(self.channels()), state['readout']['counts'])

    def test_live_roi_result_changes_only_on_calculation_and_survives_refresh(self):
        self.alpha(1)
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 3
        expect(self.page.locator('#exposure')).to_have_text('3 s')
        self.assertIsNone(self.state()['roi_result'])
        self.roi(900, 929)
        frozen = self.state()['roi_result']
        self.assertEqual(frozen['exposure_s'], 3)
        self.assertEqual(len(frozen['counts']), 1024)
        self.assertEqual(sum(frozen['counts'][900:930]), frozen['readout']['roi_counts'])
        self.assertGreater(frozen['readout']['roi_counts'], 0)
        self.now = 4
        expect(self.page.locator('#exposure')).to_have_text('4 s')
        self.assertEqual(self.state()['roi_result'], frozen)
        expect(self.page.locator('#roi-result')).to_contain_text('截止曝光 3 s')
        self.page.locator('.calibration-tools summary').click()
        for name, value in [('c1', 0), ('e1', 0), ('c2', 1000), ('e2', 6)]:
            self.page.locator(f'#calibrate [name={name}]').fill(str(value))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'calibrate') as calibrated:
            self.page.locator('#calibrate button').click()
        self.assertTrue(calibrated.value.ok, calibrated.value.text())
        self.assertEqual(self.state()['roi_result'], frozen)
        recalculated = self.roi(900, 929)
        updated = self.state()['roi_result']
        self.assertEqual(updated['exposure_s'], 4)
        self.assertNotEqual(updated['id'], frozen['id'])
        self.assertAlmostEqual(recalculated['energy_MeV'], recalculated['centroid'] * .006)
        expect(self.page.locator('#plot')).to_have_attribute(
            'aria-label', '道谱，显示 0 至 1023 道。可在谱分析中输入选区道号。')
        self.screenshot('alpha-roi-independent-four-second-recalculation')
        self.page.reload()
        expect(self.page.locator('#plot')).to_be_visible()
        self.assertEqual(self.state()['roi_result'], updated)
        empty = self.roi(0, 1)
        self.assertEqual(empty['roi_counts'], 0)
        self.assertIsNone(empty['centroid'])
        self.assertIsNone(empty['energy_MeV'])


if __name__ == '__main__':
    unittest.main()
