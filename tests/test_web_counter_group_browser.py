"""Whole-counter controls preserve window readings and save the two windows together."""
import unittest
import test_catalog_records_browser as fixtures
if fixtures.sync_playwright:
    from playwright.sync_api import expect

@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class CounterGroupBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def action(self, name, click):
        with self.page.expect_response(lambda r:r.url.endswith('/api/action') and r.request.post_data_json.get('action') == name) as response:
            click()
        self.assertTrue(response.value.ok, response.value.text())
        return response.value.json()

    def open_beta(self, seed=187):
        response=self.page.request.post(self.url+'/api/open',data={'experiment':'beta','seed':seed})
        self.assertTrue(response.ok)
        self.page.goto(self.url+'/lab/beta/#setup')

    def test_opposite_mixed_state_uses_b_running_for_status_and_controls(self):
        self.open_beta(9)
        self.page.locator('[name=source_present]').select_option('1')
        self.action('configure',lambda:self.page.get_by_role('button',name='应用参数').click())
        fixtures.enable_output(self)
        self.page.locator('#mode').select_option('count')
        self.page.locator('#count-limit').fill('11600')
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=1
        expect(self.page.locator('.counter-window[data-device=counter] .window-state')).to_have_text('到限暂停')
        expect(self.page.locator('.counter-window[data-device=counter_b] .window-state')).to_have_text('采集中')
        expect(self.page.locator('#stop')).to_be_enabled()
        expect(self.page.locator('#start')).to_be_disabled()
        expect(self.page.locator('#stop')).to_be_enabled()
        expect(self.page.locator('#mode')).to_be_disabled()
        expect(self.page.locator('#count-limit')).to_be_disabled()
        self.screenshot('step3-opposite-mixed-limit')
        self.action('stop_group',lambda:self.page.locator('#stop').click())
        expect(self.page.locator('#stop')).to_be_disabled()
        expect(self.page.locator('#mode')).to_be_enabled()

    def test_mixed_limit_then_explicit_target_change_and_common_resume(self):
        self.open_beta()
        self.page.locator('[name=source_present]').select_option('1')
        self.action('configure',lambda:self.page.get_by_role('button',name='应用参数').click())
        fixtures.enable_output(self)
        expect(self.page.locator('#device')).to_have_count(0)
        self.page.locator('#mode').select_option('count')
        self.page.locator('#count-limit').fill('11650')
        self.action('start_group',lambda:self.page.locator('#start').click())
        position=self.page.locator('#stop').bounding_box()
        self.now=1
        a=self.page.locator('.counter-window[data-device=counter]')
        b=self.page.locator('.counter-window[data-device=counter_b]')
        expect(a.locator('.window-reading strong')).to_have_text('11,603')
        expect(b.locator('.window-reading strong')).to_have_text('11,679')
        expect(a.locator('.window-state')).to_have_text('采集中')
        expect(b.locator('.window-state')).to_have_text('到限暂停')
        expect(self.page.locator('#start')).to_be_disabled()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.assertEqual(position,self.page.locator('#stop').bounding_box())
        self.screenshot('step3-mixed-limit')
        self.action('stop_group',lambda:self.page.locator('#stop').click())
        expect(self.page.locator('#start')).to_be_disabled()
        self.page.locator('#count-limit').fill('24000')
        self.action('instrument_group_config',lambda:self.page.locator('#apply-acquisition').click())
        expect(self.page.locator('#start')).to_be_enabled()
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=2
        expect(a.locator('tbody tr')).to_have_count(2)
        expect(b.locator('tbody tr')).to_have_count(2)
        state=self.page.request.get(self.url+'/api/state').json()
        self.assertEqual([state['instruments'][d]['counts'] for d in ('counter','counter_b')],[[23169],[23209]])

    def test_zero_windows_and_whole_counter_save_clear_load(self):
        self.open_beta()
        self.page.locator('[data-page=instrument]').click()
        a=self.page.locator('.counter-window[data-device=counter]')
        b=self.page.locator('.counter-window[data-device=counter_b]')
        expect(a.locator('.window-reading strong')).to_have_text('—')
        expect(self.page.locator('#current-readout,#exposure')).to_have_count(0)
        expect(self.page.locator('#counter')).not_to_contain_text('等待首个完整窗')
        self.page.locator('#window-size-counter_b').fill('5')
        self.action('window_config',lambda:self.page.locator('#window-size-counter_b').press('Tab'))
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=5
        expect(a.locator('tbody tr')).to_have_count(5)
        expect(b.locator('tbody tr')).to_have_count(1)
        expect(a.locator('.window-reading strong')).to_have_text('0')
        expect(b.locator('.window-reading strong')).to_have_text('0')
        expect(self.page.locator('#counter details')).to_have_count(0)
        self.action('stop_group',lambda:self.page.locator('#stop').click())
        fixtures.measurement_operation(self.page, 'save')
        expect(self.page.locator('#measurement-save')).not_to_be_visible()
        expect(self.page.locator('#operation-device')).to_have_count(0)
        fixtures.measurement_operation(self.page, 'clear')
        self.page.locator('#clear-discard').click()
        for panel in (a, b):
            expect(panel.locator('.window-reading strong')).to_have_text('—')
        fixtures.measurement_operation(self.page, 'cache')
        self.page.locator('#measurement-confirm').click()
        expect(a.locator('tbody tr')).to_have_count(5)
        expect(b.locator('tbody tr')).to_have_count(1)
        for panel in (a, b):
            expect(panel.locator('.window-reading strong')).to_have_text('0')
        self.screenshot('whole-counter-restored')

    def test_historical_single_window_package_keeps_instrument_and_file_controls(self):
        from dataclasses import replace
        from pathlib import Path
        from nuclemu.core import Session
        from nuclemu.exchange import capture_session, package_bytes
        from nuclemu.experiments import beta
        current=beta.EXPERIMENT
        old=replace(current, devices=(replace(current.devices[0],input=beta.DETECTOR_OUTPUT),),
                    outputs=(replace(current.outputs[0],response=beta.LEGACY_SHARED_RESPONSE),),
                    components=(), connections=(), model=beta.sample_shared_counts, restore_definition=None)
        session=Session(old,seed=187)
        session.set_output(beta.DETECTOR_OUTPUT,True)
        session.start(1)
        session.advance(1)
        session.snapshot('counter')
        path=Path(self.folder.name,'single-window.nuclemu')
        path.write_bytes(package_bytes(capture_session(session)))
        self.page.locator('#open-package').set_input_files(path)
        self.page.locator('[data-page=instrument]').click()
        expect(self.page.locator('.counter-window')).to_have_count(1)
        expect(self.page.locator('#device')).to_have_count(0)
        expect(self.page.locator('#window-size')).to_be_visible()
        expect(self.page.locator('#clear')).to_be_enabled()
        expect(self.page.get_by_role('button',name='从文件选择')).to_be_enabled()
        self.action('start',lambda:self.page.locator('#start').click())
        self.now=1
        expect(self.page.locator('.counter-window tbody tr')).to_have_count(1)
