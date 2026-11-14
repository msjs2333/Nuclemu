"""Instrument saves capture the keypress, and shared pages respect applied presets."""

from pathlib import Path
import unittest

from nuclemu.exchange import load_item, load_package
import test_catalog_records_browser as fixtures
import test_web_review_browser as review_fixtures

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class InstrumentReviewBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def action(self, name, click, *, ok=True, page=None):
        page = page or self.page
        with page.expect_response(lambda r: r.url.endswith('/api/action') and
                                  r.request.post_data_json.get('action') == name) as response:
            click()
        self.assertEqual(response.value.ok, ok, response.value.text())
        return response.value

    def instrument(self, experiment):
        self.enter(experiment)
        self.page.locator('[data-page=instrument]').click()
        fixtures.enable_output(self)

    def peer(self):
        page = self.browser.new_page(viewport={'width':1366, 'height':768})
        self.addCleanup(page.close)
        page.goto(self.url + '/lab/' + self.state()['experiment'] + '/#instrument')
        expect(page.locator('#start')).to_be_visible()
        return page

    def cutoff_roundtrip(self, experiment):
        self.instrument(experiment)
        beta = experiment == 'beta'
        start = 'start_group' if beta else 'start'
        self.action(start, lambda: self.page.locator('#start').click())
        self.now = 3
        frozen = self.action('begin_snapshot_group', lambda: self.page.locator('#save-current').click()).json()
        expect(self.page.locator('#measurement-save')).to_be_visible()
        self.assertEqual(frozen['records'], [])
        self.assertEqual(set(frozen['pending_snapshot']['exposures'].values()), {3})
        expect(self.page.locator('.snapshot-cutoff').first).to_contain_text('3 s')
        counts = {d: v['counts'] for d, v in frozen['instruments'].items()}
        self.now = 5
        live = self.state()
        self.assertTrue(live['any_running'])
        self.assertEqual({v['exposure_s'] for v in live['instruments'].values()}, {5})
        self.page.locator('#measurement-name').fill('按键时三秒')
        saved = self.action('commit_snapshot_group', lambda: self.page.locator('#measurement-save-confirm').click()).json()
        self.assertIsNone(saved['pending_snapshot'])
        self.assertEqual({s['exposure_s'] for s in saved['snapshots']}, {3})
        expect(self.page.locator('#snapshot-notice')).to_have_count(0)
        self.screenshot(experiment + '-save-cutoff-after-live-five')
        self.action('begin_snapshot_group', lambda: self.page.locator('#save-current').click())
        self.action('cancel_snapshot_group', lambda: self.page.keyboard.press('Escape'))
        self.assertEqual(len(self.state()['records']), 1)
        self.assertIsNone(self.state()['pending_snapshot'])
        self.page.locator('[data-page=records]').click()
        row = self.page.locator('#products .product')
        expect(row).to_have_count(1)
        row.locator('input').check()
        row.locator('select').select_option('json')
        with self.page.expect_download() as downloading:
            self.page.locator('#export').click()
        item_path = Path(self.folder.name, experiment + '-cutoff.json')
        downloading.value.save_as(item_path)
        item = load_item(item_path.read_bytes())
        measurements = [i['document'] for i in item['items'] if i['kind'] == 'measurement']
        self.assertEqual(len(measurements), 2 if beta else 1)
        for document in measurements:
            snapshot = document['snapshot']
            self.assertEqual(snapshot['exposure_s'], 3)
            measured = [0] * len(counts[snapshot['device']])
            for segment in document['segments']:
                for channel, count in enumerate(segment['readings'][snapshot['device']]):
                    measured[channel] += count
            self.assertEqual(measured, counts[snapshot['device']])
        with self.page.expect_download() as downloading:
            self.page.locator('#download-experiment').click()
        package_path = Path(self.folder.name, experiment + '-cutoff.nuclemu')
        downloading.value.save_as(package_path)
        package = load_package(package_path)
        expected = [i['document'] for i in package['items'] if i['kind'] == 'measurement']
        self.assertEqual(measurements, expected)
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        self.page.locator('#discard').click()
        expect(self.page.locator('#catalog')).to_be_visible()
        self.page.locator('#open-package').set_input_files(package_path)
        expect(self.page.locator('#workspace')).to_be_visible()
        with self.page.expect_download() as downloading:
            self.page.locator('[data-page=records]').click()
            self.page.locator('#download-experiment').click()
        reopened = Path(self.folder.name, experiment + '-reopened.nuclemu')
        downloading.value.save_as(reopened)
        self.assertEqual([i['document'] for i in load_package(reopened)['items'] if i['kind'] == 'measurement'], expected)

    def test_alpha_keypress_cutoff_cancel_and_real_file_reopen(self):
        self.cutoff_roundtrip('alpha')

    def test_beta_keypress_cutoff_cancel_and_real_file_reopen(self):
        self.cutoff_roundtrip('beta')

    def test_pending_save_keeps_its_old_round_and_old_token_cannot_save_a_new_one(self):
        self.instrument('beta')
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 3
        first = self.action('begin_snapshot_group', lambda: self.page.locator('#save-current').click()).json()
        peer = self.peer()
        self.action('begin_clear_group', lambda: peer.locator('#clear').click(), page=peer)
        self.action('finish_clear_group', lambda: peer.locator('#clear-discard').click(), page=peer)
        self.action('start_group', lambda: peer.locator('#start').click(), page=peer)
        self.now = 4
        committed = self.action('commit_snapshot_group', lambda: self.page.locator('#measurement-save-confirm').click()).json()
        self.assertEqual({s['exposure_s'] for s in committed['snapshots']}, {3})
        self.assertEqual({v['exposure_s'] for v in committed['instruments'].values()}, {1})
        self.assertNotEqual(committed['active_acquisition'], first['active_acquisition'])
        self.action('begin_snapshot_group', lambda: self.page.locator('#save-current').click())
        newer = self.action('begin_snapshot_group', lambda: peer.locator('#save-current').click(), page=peer).json()
        self.action('commit_snapshot_group', lambda: self.page.locator('#measurement-save-confirm').click(), ok=False)
        expect(self.page.locator('#measurement-save-error')).not_to_be_empty()
        self.assertEqual(self.state()['pending_snapshot']['token'], newer['pending_snapshot']['token'])
        self.assertEqual(len(self.state()['records']), 1)
        self.action('cancel_snapshot_group', lambda: peer.locator('#measurement-save').get_by_role('button', name='取消', exact=True).click(), page=peer)

    def test_delayed_begin_response_never_borrows_another_pages_token(self):
        self.instrument('beta')
        self.action('start_group', lambda: self.page.locator('#start').click())
        peer = self.peer()
        self.now = 3
        observed = {}
        def replace_before_response(route):
            data = route.request.post_data_json
            if data.get('action') != 'begin_snapshot_group' or observed:
                route.continue_()
                return
            original = route.fetch()
            observed['original'] = original.json()['pending_snapshot']['token']
            self.now = 4
            newer = peer.request.post(self.url + '/api/action', data=data)
            self.assertTrue(newer.ok, newer.text())
            observed['newer'] = newer.json()['pending_snapshot']['token']
            route.fulfill(response=original)
        self.page.route('**/api/action', replace_before_response)
        self.action('begin_snapshot_group', lambda: self.page.locator('#save-current').click())
        self.page.unroute('**/api/action', replace_before_response)
        expect(self.page.locator('#measurement-save')).to_be_visible()
        self.assertNotEqual(observed['original'], observed['newer'])
        rejected = self.action('commit_snapshot_group', lambda: self.page.locator('#measurement-save-confirm').click(), ok=False)
        self.assertEqual(rejected.request.post_data_json['token'], observed['original'])
        self.assertEqual(self.state()['pending_snapshot']['token'], observed['newer'])
        self.assertEqual(self.state()['records'], [])
        self.screenshot('delayed-save-response-rejects-original-token')

    def shared_forms(self, experiment):
        self.instrument(experiment)
        config = 'instrument_group_config' if experiment == 'beta' else 'instrument_config'
        start = 'start_group' if experiment == 'beta' else 'start'
        stop = 'stop_group' if experiment == 'beta' else 'stop'
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('10')
        self.action(config, lambda: self.page.locator('#apply-acquisition').click())
        peer = self.peer()
        expect(peer.locator('#duration')).to_have_value('10')
        peer.locator('#duration').fill('20')
        self.action(config, lambda: peer.locator('#apply-acquisition').click(), page=peer)
        expect(self.page.locator('#duration')).to_have_value('20')
        requests = []
        self.page.on('request', lambda request: requests.append(request.post_data_json['action'])
                     if request.url.endswith('/api/action') else None)
        self.action(start, lambda: self.page.locator('#start').click())
        self.assertNotIn(config, requests)
        self.now = 11
        self.assertTrue(self.state()['running'])
        self.assertEqual(self.state()['instrument']['duration_s'], 20)
        self.action(stop, lambda: self.page.locator('#stop').click())
        self.page.locator('#duration').fill('30')
        peer.locator('#duration').fill('40')
        self.action(config, lambda: peer.locator('#apply-acquisition').click(), page=peer)
        expect(self.page.locator('#acquisition-error')).to_contain_text('其他页面')
        requests.clear()
        self.page.locator('#start').click()
        expect(self.page.locator('#acquisition-error')).to_contain_text('应用')
        self.assertEqual(requests, [])
        expect(self.page.locator('#duration')).to_have_value('30')
        self.assertEqual(self.state()['instrument']['duration_s'], 40)
        self.action(config, lambda: self.page.locator('#apply-acquisition').click())
        self.assertEqual(self.state()['instrument']['duration_s'], 30)
        # Hold only A's poll so the request itself, not UI detection, must reject stale input.
        frozen = self.state()
        release = review_fixtures.WebReviewBrowserTests.hold_poll(self.page, frozen)
        self.page.locator('#duration').fill('50')
        expect(peer.locator('#duration')).to_have_value('30')
        peer.locator('#duration').fill('60')
        self.action(config, lambda: peer.locator('#apply-acquisition').click(), page=peer)
        rejected = self.action(config, lambda: self.page.locator('#start').click(), ok=False)
        self.assertEqual(rejected.request.post_data_json['expected']['duration_s'], 30)
        expect(self.page.locator('#acquisition-error')).to_contain_text('改变')
        expect(self.page.locator('#duration')).to_have_value('50')
        self.assertFalse(self.state()['running'])
        self.assertEqual(self.state()['instrument']['duration_s'], 60)
        release()
        self.screenshot(experiment + '-shared-preset-conflict')

    def test_alpha_shared_presets_sync_and_reject_stale_start(self):
        self.shared_forms('alpha')

    def test_beta_shared_presets_sync_and_reject_stale_start(self):
        self.shared_forms('beta')

    def test_spectrum_tabs_move_focus_selection_and_panel_relationships(self):
        self.instrument('alpha')
        acquisition = self.page.get_by_role('tab', name='采集', exact=True)
        analysis = self.page.get_by_role('tab', name='谱分析', exact=True)
        acquisition.focus()
        for key, selected, hidden in [('ArrowRight', analysis, acquisition), ('ArrowRight', acquisition, analysis),
                                      ('End', analysis, acquisition), ('Home', acquisition, analysis),
                                      ('ArrowLeft', analysis, acquisition)]:
            self.page.keyboard.press(key)
            expect(selected).to_be_focused()
            expect(selected).to_have_attribute('aria-selected', 'true')
            expect(selected).to_have_attribute('tabindex', '0')
            expect(hidden).to_have_attribute('aria-selected', 'false')
            expect(hidden).to_have_attribute('tabindex', '-1')
            panel = self.page.locator('#' + selected.get_attribute('aria-controls'))
            expect(panel).to_be_visible()
            expect(panel).to_have_attribute('role', 'tabpanel')
            expect(panel).to_have_attribute('aria-labelledby', selected.get_attribute('id'))
        self.screenshot('spectrum-tabs-keyboard-analysis')

    def test_unchanged_polls_keep_a_draft_startable(self):
        self.instrument('beta')
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('12')
        for _ in range(3):
            with self.page.expect_response(lambda r: '/api/state?' in r.url):
                pass
        expect(self.page.locator('#acquisition-error')).to_have_count(0)
        expect(self.page.locator('#duration')).to_have_value('12')
        # Independent window settings do not conflict with this shared target draft.
        peer = self.peer()
        peer.locator('#window-size-counter_b').fill('5')
        self.action('window_config', lambda: peer.locator('#window-size-counter_b').press('Tab'), page=peer)
        for _ in range(2):
            with self.page.expect_response(lambda r: '/api/state?' in r.url):
                pass
        expect(self.page.locator('#acquisition-error')).to_have_count(0)
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.assertTrue(self.state()['running'])
        self.assertEqual(self.state()['instrument']['duration_s'], 12)


if __name__ == '__main__':
    unittest.main()
