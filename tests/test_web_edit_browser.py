"""Browser checks for local parameter drafts and acquisition-bound stop buttons."""

from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
import test_web_review_browser as review
from nuclemu.catalog import discover

if fixtures.sync_playwright:
    from playwright.sync_api import expect


MULTI = """
from nuclemu.core import Component, Device, Experiment, Parameter
EXPERIMENT = Experiment('edit-review', '参数编辑', '',
    (Parameter('gain', '增益', '', 1, 1, 8, True),
     Parameter('threshold', '阈值', '', 1, 1, 8, True)),
    (Device('counter', 'counter', '计数器'),),
    lambda settings, start, end, rng: {'counter': [round((end-start)*20)]},
    components=(Component('controls', 'electronics', '电子学', parameters=('gain', 'threshold')),
                Component('other', 'electronics', '阈值部件', parameters=('threshold',)),
                Component('meter', 'instrument', '计数器', device='counter')))
"""


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class WebEditBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    peer = review.WebReviewBrowserTests.peer
    state = review.WebReviewBrowserTests.state
    start = review.WebReviewBrowserTests.start
    exit_dialog = review.WebReviewBrowserTests.exit_dialog
    hold_poll = staticmethod(review.WebReviewBrowserTests.hold_poll)

    def editors(self):
        Path(self.folder.name, 'edit.py').write_text(MULTI, encoding='utf-8')
        self.server.app.definitions = discover([self.folder.name])
        self.page.reload()
        peer = self.peer()
        self.enter('edit-review')
        peer.locator("[data-experiment='edit-review']").click()
        expect(peer.locator('#workspace')).to_be_visible()
        self.page.locator('[data-part=controls]').click()
        peer.locator('[data-part=controls]').click()
        return peer

    def apply(self, page):
        page.locator('#component form button').click()
        expect(page.locator('#component form button')).to_be_enabled()

    def merged_fields(self, refresh):
        peer = self.editors()
        self.page.locator('[name=gain]').fill('2')
        release = self.hold_poll(self.page, self.state())
        peer.locator('[name=threshold]').fill('3')
        self.apply(peer)
        expect(peer.locator('#message')).to_contain_text('已更新')
        if refresh:
            release()
            expect(self.page.locator('[name=threshold]')).to_have_value('3')
            expect(self.page.locator('[name=gain]')).to_have_value('2')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'configure') as pending:
            self.apply(self.page)
        self.assertEqual(pending.value.request.post_data_json['values'], {'gain': 2})
        self.assertEqual(self.state()['settings'], {'gain': 2, 'threshold': 3})
        release()
        self.exit_dialog(self.page)
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#catalog')).to_be_visible()
        self.page.get_by_role('button', name='查看实验', exact=True).click()
        expect(self.page.locator('#workspace')).to_be_visible()
        self.assertEqual(self.state()['settings'], {'gain': 2, 'threshold': 3})

    def test_local_gain_merges_remote_threshold_before_poll(self):
        self.merged_fields(False)

    def test_local_gain_survives_poll_and_merges_remote_threshold(self):
        self.merged_fields(True)

    def test_failed_submit_and_typing_during_submit_keep_local_draft(self):
        peer = self.editors()
        routes = []
        self.page.route('**/api/action', lambda route: routes.append(route))
        self.page.locator('[name=gain]').fill('2')
        self.page.locator('#component form button').click()
        self.page.wait_for_function("document.querySelector('#component form button').disabled")
        self.page.locator('[name=gain]').fill('4')
        routes.pop().fulfill(status=400, json={'error': 'edit review failure'})
        expect(self.page.locator('#component [role=alert]')).to_contain_text('edit review failure')
        expect(self.page.locator('[name=gain]')).to_have_value('4')
        self.page.locator('#component form button').click()
        self.page.wait_for_function("document.querySelector('#component form button').disabled")
        self.page.locator('[name=gain]').fill('1')
        self.page.locator('[name=threshold]').fill('2')
        self.page.locator('[name=threshold]').fill('1')
        peer.locator('[name=threshold]').fill('3')
        self.apply(peer)
        expect(peer.locator('#message')).to_contain_text('已更新')
        routes.pop().continue_()
        expect(self.page.locator('#component form button')).to_be_enabled()
        expect(self.page.locator('[name=gain]')).to_have_value('1')
        self.assertEqual(self.state()['settings']['gain'], 4)
        expect(self.page.locator('[name=threshold]')).to_have_value('3')
        self.page.unroute('**/api/action')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action')) as pending:
            self.apply(self.page)
        self.assertEqual(pending.value.request.post_data_json['values'], {'gain': 1})
        self.assertEqual(self.state()['settings']['gain'], 1)
        self.assertEqual(self.state()['settings']['threshold'], 3)

    def test_restore_original_and_switch_component_drop_unsubmitted_edits(self):
        peer = self.editors()
        self.page.locator('[name=gain]').fill('2')
        self.page.locator('[name=gain]').fill('1')
        peer.locator('[name=gain]').fill('3')
        self.apply(peer)
        expect(self.page.locator('[name=gain]')).to_have_value('3')
        self.page.locator('[name=gain]').fill('2')
        peer.locator('[name=gain]').fill('4')
        self.apply(peer)
        expect(self.page.locator('[name=threshold]')).to_have_value('1')
        self.page.wait_for_timeout(600)
        expect(self.page.locator('[name=gain]')).to_have_value('2')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action')) as pending:
            self.apply(self.page)
        self.assertEqual(pending.value.request.post_data_json['values'], {'gain': 2})
        self.assertEqual(self.state()['settings']['gain'], 2)
        self.page.locator('[name=gain]').fill('5')
        self.page.locator('[data-part=other]').click()
        self.page.locator('[data-part=controls]').click()
        expect(self.page.locator('[name=gain]')).to_have_value('2')

    def test_stale_stop_cannot_close_new_gate_and_current_stop_settles_tail(self):
        peer = self.peer()
        self.enter('beta')
        self.start(10)
        peer.locator("[data-experiment='beta']").click()
        peer.locator("[data-page='instrument']").click()
        original = self.state()
        release = self.hold_poll(self.page, original)
        self.now = .25
        peer.locator('#stop').click()
        expect(peer.locator('#start')).to_be_enabled()
        paused = self.state()
        peer.locator('#start').click()
        expect(peer.locator('#stop')).to_be_enabled()
        self.now += .375
        before = self.state()
        self.assertEqual(before['active_acquisition'], original['active_acquisition'])
        self.assertNotEqual(before['instrument']['cycle'], original['instrument']['cycle'])
        with self.page.expect_response(lambda r: r.url.endswith('/api/action')) as rejected:
            self.page.locator('#stop').click()
        self.assertEqual(rejected.value.status, 400)
        self.assertEqual(rejected.value.request.post_data_json['device'], original['device'])
        self.assertEqual(rejected.value.request.post_data_json['acquisition'], original['active_acquisition'])
        self.assertEqual(rejected.value.request.post_data_json['cycle'], original['instrument']['cycle'])
        after = self.state()
        self.assertTrue(after['running'])
        self.assertEqual(after['remaining_s'], before['remaining_s'])
        self.assertEqual(after['product'], before['product'])
        release()
        peer.locator('#stop').click()
        expect(peer.locator('#start')).to_be_enabled()
        final = self.state()
        self.assertFalse(final['running'])
        self.assertIsNone(final['active_acquisition'])
        self.assertEqual(final['instrument']['acquisition'], original['instrument']['acquisition'])
        self.assertEqual(final['instrument']['exposure_s'] - paused['instrument']['exposure_s'], .375)
        self.assertEqual(final['product']['segments'][-1]['end_s'] -
                         final['product']['segments'][-1]['start_s'], .625)


if __name__ == '__main__':
    unittest.main()
