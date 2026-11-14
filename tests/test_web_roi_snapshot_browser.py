"""Explicit ROI calculation freezes its measurement while acquisition continues."""
import unittest
import test_catalog_records_browser as fixtures
if fixtures.sync_playwright:
    from playwright.sync_api import expect

@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class RoiSnapshotBrowserTests(unittest.TestCase):
    setUp=fixtures.CatalogRecordsBrowserTests.setUp
    stop_server=fixtures.CatalogRecordsBrowserTests.stop_server
    enter=fixtures.CatalogRecordsBrowserTests.enter
    screenshot=fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url+'/api/state').json()

    def action(self, name, click):
        with self.page.expect_response(lambda r:r.url.endswith('/api/action') and r.request.post_data_json.get('action')==name) as response:
            click()
        self.assertTrue(response.value.ok,response.value.text())
        return response.value.json()

    def test_fixed_full_extent_frozen_result_and_resizable_controls(self):
        self.enter('alpha')
        self.page.locator('[name=source_present]').select_option('1')
        self.action('configure',lambda:self.page.get_by_role('button',name='应用参数').click())
        fixtures.enable_output(self)
        expect(self.page.locator('#plot')).to_have_attribute('aria-label', '道谱，显示 0 至 1023 道。可在谱分析中输入选区道号。')
        self.action('start',lambda:self.page.locator('#start').click())
        self.now=3
        expect(self.page.locator('#exposure')).to_have_text('3 s')
        self.page.get_by_role('tab',name='谱分析',exact=True).click()
        self.page.locator('#first').fill('900')
        self.page.locator('#last').fill('929')
        calculated=self.action('calculate_roi',lambda:self.page.locator('#roi button').click())['roi_result']
        self.assertEqual(calculated['exposure_s'],3)
        self.assertEqual(calculated['roi'],[900,929])
        self.assertEqual(len(calculated['counts']),1024)
        self.now=4
        expect(self.page.locator('#exposure')).to_have_text('4 s')
        self.assertEqual(self.state()['roi_result'],calculated)
        expect(self.page.locator('#roi-result')).to_contain_text('截止曝光 3 s')
        bounds=self.page.locator('#roi-result').bounding_box()
        self.assertLessEqual(bounds['y']+bounds['height'],768)
        expect(self.page.locator('#plot')).to_have_attribute('aria-label', '道谱，显示 0 至 1023 道。可在谱分析中输入选区道号。')
        self.screenshot('roi-frozen-four-second-live')
        divider=self.page.get_by_role('separator',name='调整仪器操作栏宽度')
        before=self.page.locator('.instrument-controls').bounding_box()['width']
        point=divider.bounding_box()
        self.page.mouse.move(point['x']+3,point['y']+80)
        self.page.mouse.down()
        self.page.mouse.move(point['x']-77,point['y']+80)
        self.page.mouse.up()
        after=self.page.locator('.instrument-controls').bounding_box()['width']
        self.assertGreater(after,before+60)
        self.page.locator('.calibration-tools summary').click()
        for field,value in [('c1','0'),('e1','0'),('c2','1000'),('e2','6')]:
            self.page.locator('[name='+field+']').fill(value)
        self.action('calibrate',lambda:self.page.locator('#calibrate button').click())
        self.assertEqual(self.state()['roi_result'],calculated)
        fresh=self.action('calculate_roi',lambda:self.page.locator('#roi button').click())['roi_result']
        self.assertNotEqual(fresh['id'],calculated['id'])
        self.assertEqual(fresh['exposure_s'],4)
        self.assertIsNotNone(fresh['readout']['energy_MeV'])
        self.screenshot('roi-recalculated-and-resized')
