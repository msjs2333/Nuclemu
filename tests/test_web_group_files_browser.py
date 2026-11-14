"""Named whole-instrument records preserve real partial exposure and stable identity."""
from pathlib import Path
import unittest
import test_catalog_records_browser as fixtures
from nuclemu.exchange import load_item
if fixtures.sync_playwright:
    from playwright.sync_api import expect

@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright')
class GroupFilesBrowserTests(unittest.TestCase):
    setUp=fixtures.CatalogRecordsBrowserTests.setUp
    stop_server=fixtures.CatalogRecordsBrowserTests.stop_server
    enter=fixtures.CatalogRecordsBrowserTests.enter
    screenshot=fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url+'/api/state').json()

    def action(self,name,click):
        with self.page.expect_response(lambda r:r.url.endswith('/api/action') and r.request.post_data_json.get('action')==name) as response:
            click()
        self.assertTrue(response.value.ok,response.value.text())
        return response.value.json()

    def save(self,name):
        self.page.locator('#save-current').click()
        expect(self.page.locator('#measurement-name')).to_have_value(__import__('re').compile(r'^BABS_\d{8}-\d{6}$'))
        self.page.locator('#measurement-name').fill(name)
        return self.action('snapshot_group',lambda:self.page.locator('#measurement-save-confirm').click())

    def test_named_group_partial_csv_rename_clear_and_resume(self):
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#window-size-counter_b').fill('5')
        self.action('window_config',lambda:self.page.locator('#window-size-counter_b').press('Tab'))
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=3
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(3)
        first=self.save('课堂测量')
        identity=first['records'][0]['id']
        self.assertEqual(len(first['records']),1)
        self.assertEqual([r['exposure_s'] for r in first['records'][0]['measurements']],[3,3])
        expect(self.page.locator('.counter-window[data-device=counter_b] .window-reading strong')).to_have_text('—')
        self.now=5
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(5)
        second=self.save('课堂测量')
        self.assertEqual(len(second['records']),2)
        self.assertNotEqual(second['records'][0]['id'],second['records'][1]['id'])
        self.action('stop_group',lambda:self.page.locator('#stop').click())
        self.page.locator('[data-page=records]').click()
        row=self.page.locator(f'#products [data-key="r/{identity}"]')
        row.locator('input').check()
        with self.page.expect_download() as downloading:
            self.page.locator('#export').click()
        path=Path(self.folder.name,downloading.value.suggested_filename)
        downloading.value.save_as(path)
        document=load_item(path.read_bytes())
        measurements=[i for i in document['items'] if i['kind']=='measurement']
        self.assertEqual(len(measurements),2)
        by_device={i['document']['snapshot']['device']:i['document'] for i in measurements}
        self.assertEqual(len(by_device['counter']['windows']),3)
        self.assertEqual(len(by_device['counter_b']['windows']),1)
        self.assertFalse(by_device['counter_b']['windows'][0]['complete'])
        self.assertEqual(by_device['counter_b']['snapshot']['exposure_s'],3)
        self.page.locator(f'[data-rename-record="{identity}"]').click()
        self.page.locator('#record-name').fill('重命名测量')
        self.action('rename_record',lambda:self.page.locator('#rename-confirm').click())
        expect(row).to_contain_text('重命名测量')
        expect(row.locator('input')).to_be_checked()
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'),1366)
        select=row.locator('select').bounding_box()
        self.assertLessEqual(select['x']+select['width'],1366)
        self.assertTrue(row.locator('.product-exposure').evaluate('(el)=>el.scrollWidth<=el.clientWidth'))
        self.screenshot('named-group-record-and-format')
        self.page.locator('[data-page=instrument]').click()
        before=self.state()['instruments']
        self.action('begin_clear_group',lambda:self.page.locator('#clear').click())
        self.action('finish_clear_group',lambda:self.page.locator('#clear-cancel').click())
        self.assertEqual(self.state()['instruments'],before)
        self.action('begin_clear_group',lambda:self.page.locator('#clear').click())
        self.action('finish_clear_group',lambda:self.page.locator('#clear-discard').click())
        self.assertEqual([v['exposure_s'] for v in self.state()['instruments'].values()],[0,0])
        with self.page.expect_file_chooser() as choosing:
            self.page.get_by_role('button',name='从文件选择',exact=True).click()
        choosing.value.set_files(path)
        expect(self.page.locator('#measurement-load')).to_be_visible()
        self.action('load_measurement',lambda:self.page.locator('#measurement-confirm').click())
        self.assertEqual([v['exposure_s'] for v in self.state()['instruments'].values()],[3,3])
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=7
        expect(self.page.locator('.counter-window[data-device=counter] tbody tr')).to_have_count(5)
        expect(self.page.locator('.counter-window[data-device=counter_b] .unfinished-window')).to_have_count(0)
        self.screenshot('group-file-loaded-and-resumed')

    def test_missing_side_stays_empty_and_old_single_automatically_preserves_other_side(self):
        import test_exchange_restore_definition as historical
        from nuclemu.exchange import export_item
        old=historical.BetaSavedModeTests().old_document()
        original=next(i for i in old['items'] if i['document']['snapshot']['device']=='counter')
        single=Path(self.folder.name,'historical-one-window.csv')
        single.write_bytes(export_item(old,original['id'],'csv'))
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        def choose(path):
            with self.page.expect_file_chooser() as choosing:
                self.page.get_by_role('button',name='从文件选择',exact=True).click()
            choosing.value.set_files(path)
            expect(self.page.locator('#measurement-load')).to_be_visible()
        choose(single)
        expect(self.page.locator('#measurement-load')).to_contain_text('历史单窗读数')
        self.action('load_measurement',lambda:self.page.locator('#measurement-confirm').click())
        self.assertEqual(self.state()['instruments']['counter_b']['exposure_s'],0)
        saved=self.save('只有实际读出的A')
        self.assertEqual(len(saved['snapshots']),1)
        self.page.locator('[data-page=records]').click()
        self.page.locator('#products .product input').check()
        with self.page.expect_download() as downloading:
            self.page.locator('#export').click()
        grouped=Path(self.folder.name,downloading.value.suggested_filename)
        downloading.value.save_as(grouped)
        doc=load_item(grouped.read_bytes())
        self.assertEqual(len([i for i in doc['items'] if i['kind']=='measurement']),1)
        self.page.locator('[data-page=instrument]').click()
        self.action('start_group',lambda:self.page.locator('#start').click())
        self.now=1
        expect(self.page.locator('.counter-window[data-device=counter_b] tbody tr')).to_have_count(1)
        self.action('stop_group',lambda:self.page.locator('#stop').click())
        before=self.state()['instruments']['counter_b']
        choose(single)
        self.action('load_measurement',lambda:self.page.locator('#measurement-confirm').click())
        self.assertEqual(self.state()['instruments']['counter_b'],before)
        choose(grouped)
        expect(self.page.locator('#measurement-load')).not_to_contain_text('历史单窗读数')
        self.action('load_measurement',lambda:self.page.locator('#measurement-confirm').click())
        self.assertEqual(self.state()['instruments']['counter_b']['exposure_s'],0)
        expect(self.page.locator('.counter-window[data-device=counter_b] .window-reading strong')).to_have_text('—')
        self.screenshot('group-missing-side-remains-empty')
