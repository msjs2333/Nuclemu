"""The replacement dialog must honor save, failure, discard and download return."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_catalog_records_browser as fixtures
from nuclemu.core import Session
from nuclemu.exchange import capture_session, package_bytes
from nuclemu.web_session import Application

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright for desktop checks')
class ReplaceSaveBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def replacement(self):
        path = Path(self.folder.name, 'beta.nuclemu')
        path.write_bytes(package_bytes(capture_session(Session(self.server.app.definitions['beta']))))
        self.page.locator('#menu-file').click()
        with self.page.expect_file_chooser() as choosing:
            self.page.locator('#load-experiment').click()
        choosing.value.set_files(path)
        expect(self.page.locator('#exit-title')).to_have_text('载入前是否保存实验？')

    def old_archive(self):
        name = fixtures.install_legacy(self, 'alpha')
        # Build one actual old-protocol archive, then use its visible viewer.
        app = self.server.app
        with self.server.app_lock:
            app.open(dict(experiment=name))
            lab = app.lab
            app.request('/api/action', dict(session=lab.id, action='start', duration=2))
            self.now = 1
            app.request('/api/action', dict(session=lab.id, action='save', exit=False))
            identity = lab.archive_id
            original = deepcopy(app.store.read(identity))
            app.lab = None
        response = self.page.request.post(self.url + '/api/open', data={'archive': identity})
        self.assertTrue(response.ok, response.text())
        self.page.goto(self.url + '/lab/' + name + '/#instrument')
        expect(self.page.locator('#plot')).to_be_visible()
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('#first').fill('12')
        self.page.locator('#last').fill('34')
        self.page.locator('#roi button').click()
        expect(self.page.locator('#roi-result')).to_contain_text('ROI 12–34')
        return identity, original

    def test_historical_save_before_replacement_reopens_copy_and_preserves_source(self):
        identity, original = self.old_archive()
        copied_id = self.server.app.lab.archive_id
        self.replacement()
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#lab-title')).to_contain_text('β')
        app = self.server.app
        self.assertEqual(app.store.read(identity), original)
        reopened = Application(app.definitions, self.folder.name, lambda: self.now)
        state = reopened.open(dict(archive=copied_id))
        self.assertEqual(state['analysis']['roi'], [12, 34])
        self.assertEqual(state['product'], original['product'])

    def test_failed_save_can_return_and_discard_does_not_create_copy(self):
        identity, original = self.old_archive()
        lab = self.server.app.lab
        self.replacement()
        with patch.object(self.server.app.store, 'write', side_effect=OSError('archive disk failed')):
            self.page.locator('#save-exit').click()
            expect(self.page.locator('#exit-error')).to_contain_text('archive disk failed')
        self.assertIs(self.server.app.lab, lab)
        self.assertEqual(self.state()['analysis']['roi'], [12, 34])
        self.page.locator('#cancel').click()
        expect(self.page.locator('#confirm')).not_to_be_visible()
        self.replacement()
        self.page.locator('#discard').click()
        expect(self.page.locator('#lab-title')).to_contain_text('β')
        archives = [r for r in self.server.app.store.list() if r['kind'] == 'archive']
        self.assertEqual([r['id'] for r in archives], [identity])
        self.assertEqual(self.server.app.store.read(identity), original)

    def test_modern_replacement_download_cancel_keeps_the_original_session(self):
        self.enter('alpha')
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1
        expect(self.page.locator('#exposure')).to_have_text('1 s')
        fixtures.measurement_operation(self.page, 'save')
        self.assertEqual(len(self.state()['snapshots']), 1)
        before = self.state()
        self.replacement()
        self.page.route('**/api/download', lambda route: route.fulfill(status=500, json={'error': 'download failed'}))
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#exit-error')).to_contain_text('download failed')
        self.assertEqual(self.state()['id'], before['id'])
        self.page.unroute('**/api/download')
        with self.page.expect_download() as downloading:
            self.page.locator('#save-exit').click()
        downloading.value.cancel()
        expect(self.page.locator('#exit-download-status')).to_contain_text('请确认文件已保存')
        self.assertEqual(self.state()['id'], before['id'])
        self.page.locator('#cancel').click()
        expect(self.page.locator('#confirm')).not_to_be_visible()
        self.assertEqual(self.state()['id'], before['id'])
        self.assertTrue(self.state()['running'])
        self.assertEqual(self.state()['snapshots'], before['snapshots'])
        self.assertEqual(self.server.app.catalog()['archives'], [])
