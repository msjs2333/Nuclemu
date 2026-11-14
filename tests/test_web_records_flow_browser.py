"""Current records and exit downloads retain student data and saved history."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import test_catalog_records_browser as fixtures
from nuclemu.exchange import load_package
from nuclemu.web import make_server
if fixtures.sync_playwright:
    from playwright.sync_api import expect

@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class RecordsFlowBrowserTests(unittest.TestCase):
    setUp=fixtures.CatalogRecordsBrowserTests.setUp
    stop_server=fixtures.CatalogRecordsBrowserTests.stop_server
    enter=fixtures.CatalogRecordsBrowserTests.enter
    screenshot=fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url+'/api/state').json()

    def test_save_at_three_round_at_five_reopen_and_failed_exit_download(self):
        self.enter('beta')
        self.page.locator('[data-page=records]').click()
        expect(self.page.locator('#products')).to_have_text('当前没有实验记录，请进行测量或在本页面导入')
        self.page.locator('[data-page=instrument]').click()
        with self.page.expect_response(lambda r:r.url.endswith('/api/action') and r.request.post_data_json.get('action')=='start_group'):
            self.page.locator('#start').click()
        self.now=3
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(3)
        self.page.locator('#save-current').click()
        self.page.locator('#measurement-name').fill('3秒保存')
        with self.page.expect_response(lambda r:r.url.endswith('/api/action') and r.request.post_data_json.get('action')=='snapshot_group') as response:
            self.page.locator('#measurement-save-confirm').click()
        self.assertTrue(response.value.ok,response.value.text())
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        expect(self.page.locator('#confirm')).to_be_visible()
        expect(self.page.locator('#exit-message')).to_have_count(0)
        self.page.locator('#cancel').click()
        self.now=5
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(5)
        self.page.locator('#stop').click()
        expect(self.page.locator('#stop')).to_be_disabled()
        self.page.locator('[data-page=records]').click()
        expect(self.page.locator('#products .product')).to_have_count(1)
        row=self.page.locator('#products .product')
        row.locator('input').check()
        original=self.state()
        self.page.locator('#menu-file').click()
        expect(self.page.locator('#panel-file button')).to_have_text(['载入实验','保存实验','退出实验'])
        self.page.locator('#leave').click()
        expect(self.page.locator('#confirm')).to_be_visible()
        expect(self.page.locator('#exit-title')).to_have_text('退出前是否保存实验？')
        expect(self.page.locator('#confirm')).not_to_contain_text('仿真时钟冻结')
        expect(self.page.locator('#confirm')).not_to_contain_text('本场缓存只保留')
        self.assertEqual(self.page.locator('#confirm button:visible').count(),3)
        self.screenshot('exit-save-discard-cancel')
        def fail_download(route):
            route.fulfill(status=500,json={'error':'下载写入测试失败，请重试'})
        self.page.route('**/api/download',fail_download)
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#exit-error')).to_contain_text('下载写入测试失败')
        self.assertEqual(self.state()['snapshots'],original['snapshots'])
        self.page.unroute('**/api/download',fail_download)
        self.page.locator('#cancel').click()
        expect(self.page.locator('#confirm')).not_to_be_visible()
        expect(self.page.locator('[data-page=records]')).to_have_attribute('aria-current','page')
        expect(row.locator('input')).to_be_checked()
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        with self.page.expect_download() as downloading:
            self.page.locator('#save-exit').click()
        path=Path(self.folder.name,downloading.value.suggested_filename)
        downloading.value.save_as(path)
        expect(self.page.locator('#exit-after-download')).to_be_visible()
        self.assertEqual(self.page.locator('#confirm button:visible').count(),2)
        self.assertIsNotNone(self.state())
        self.page.locator('#cancel').click()
        expect(row.locator('input')).to_be_checked()
        package=load_package(path)
        self.assertEqual([r['exposure_s'] for r in package['rounds']],[5,5])
        self.assertEqual([i['document']['snapshot']['exposure_s'] for i in package['items'] if i['kind']=='measurement'],[3,3])
        self.screenshot('exit-download-return-retains-record')
        with TemporaryDirectory() as directory, make_server(directory=directory,clock=lambda:self.now) as server:
            worker=Thread(target=server.serve_forever)
            worker.start()
            page=self.browser.new_page(viewport={'width':1366,'height':768})
            try:
                url=f'http://127.0.0.1:{server.server_port}'
                page.goto(url)
                page.locator('#open-package').set_input_files(path)
                expect(page.locator('#workspace')).to_be_visible()
                state=page.request.get(url+'/api/state').json()
                self.assertFalse(state['any_running'])
                self.assertEqual([i['exposure_s'] for i in state['instruments'].values()],[0,0])
                self.assertEqual(len(state['records']),1)
                self.assertEqual([s['exposure_s'] for s in state['snapshots']],[3,3])
                page.locator('[data-page=instrument]').click()
                page.get_by_role('button',name='从本场实验记录选择').click()
                expect(page.locator('#measurement-load')).to_be_visible()
                page.locator('#measurement-confirm').click()
                expect(page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(3)
                restored=page.request.get(url+'/api/state').json()
                self.assertEqual([i['exposure_s'] for i in restored['instruments'].values()],[3,3])
            finally:
                page.close()
                server.shutdown()
                worker.join()
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        self.page.locator('#discard').click()
        expect(self.page.locator('#catalog')).to_be_visible()
        self.assertIsNone(self.state())
