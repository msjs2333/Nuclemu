"""Import choices name complete instrument readings and keep both source members."""
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.core import Session
from nuclemu.exchange import (cache_calibration, capture_session, export_item, link_measurements,
    load_item, native_snapshot_id, package_bytes)
from nuclemu.experiments import beta
from nuclemu.experiments.alpha import EXPERIMENT as ALPHA
from nuclemu.results import Calibration

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright for desktop checks')
class RecordImportBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter

    def inspect(self, path):
        with self.page.expect_file_chooser() as choosing:
            self.page.locator('#choose-import').click()
        choosing.value.set_files(path)
        expect(self.page.locator('#import-choice')).to_be_visible()

    def test_group_json_csv_package_are_one_named_choice_and_keep_both_windows(self):
        source = Session(beta.EXPERIMENT, seed=187)
        source.set('source_present', 1)
        source.set_output('beta_detector', True)
        source.configure_acquisition('counter_b', window_s=5)
        source.start_group(('counter', 'counter_b'))
        source.advance(3)
        snapshots = source.snapshot_group(('counter', 'counter_b'))
        doc = capture_session(source)
        identity = link_measurements(doc, [native_snapshot_id(doc, s) for s in snapshots],
                                     '三秒读数', members=('counter', 'counter_b'))
        files = {'json': export_item(doc, identity, 'json'), 'csv': export_item(doc, identity, 'csv'),
                 'nuclemu': package_bytes(doc)}
        self.enter('beta')
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1
        fixtures.expect_counter_exposure(self.page, 1)
        before = self.page.request.get(self.url + '/api/state').json()['instruments']
        self.page.locator('[data-page=records]').click()
        for count, (fmt, raw) in enumerate(files.items(), 1):
            with self.subTest(format=fmt):
                path = Path(self.folder.name, 'source.' + fmt)
                path.write_bytes(raw)
                self.inspect(path)
                options = self.page.locator('#import-selection option')
                expect(options).to_have_count(1)
                expect(options).to_contain_text(['窗 A · 3 s；计数器 · 窗 B · 3 s'])
                self.assertNotIn('counter', options.inner_text())
                with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                               r.request.post_data_json.get('action') == 'import_item') as imported:
                    self.page.locator('#confirm-import').click()
                self.assertTrue(imported.value.ok, imported.value.text())
                state = imported.value.json()
                self.assertEqual(state['instruments'], before)
                self.assertEqual(len(state['records']), count)
                lab = self.server.app.lab
                copied = lab.exchange.document['items'][-2:]
                self.assertEqual([i['document'] for i in copied], [i['document'] for i in doc['items']])
                for item in copied:
                    indices = lab.work.lab.view.item_indices[item['id']]
                    device = item['document']['snapshot']['device']
                    self.assertTrue(indices)
                    self.assertEqual(sum(state['product']['segments'][i]['readings'][device][0] for i in indices),
                                     sum(p['readings'][device][0] for p in item['document']['segments']))
                self.assertEqual({d for p in state['product']['segments'] for d in p['readings']},
                                 {'counter', 'counter_b'})
                row = self.page.locator(f'[data-key="r/{state["records"][-1]["id"]}"]')
                row.locator('input').check()
                row.locator('select').select_option('csv')
                with self.page.expect_download() as download:
                    self.page.locator('#export').click()
                output = Path(self.folder.name, 'roundtrip-' + fmt + '.csv')
                download.value.save_as(output)
                bundle = load_item(output)
                self.assertEqual([i['document'] for i in bundle['items']], [i['document'] for i in doc['items']])
                row.locator('input').uncheck()
                self.assertEqual(path.read_bytes(), raw)

    def test_true_single_window_choice_uses_window_name(self):
        source = Session(beta.EXPERIMENT)
        source.start(1, device='counter_b')
        source.advance(1)
        source.snapshot('counter_b')
        doc = capture_session(source)
        path = Path(self.folder.name, 'single.csv')
        path.write_bytes(export_item(doc, doc['items'][0]['id'], 'csv'))
        self.enter('beta')
        self.page.locator('[data-page=records]').click()
        self.inspect(path)
        option = self.page.locator('#import-selection option')
        expect(option).to_have_count(1)
        expect(option).to_contain_text(['计数器 · 窗 B · 单窗读数 · 1 s'])
        self.assertNotIn('counter_b', option.inner_text())

    def test_calibration_choice_names_its_instrument_and_quantity(self):
        doc = capture_session(Session(ALPHA))
        identity = cache_calibration(doc, Calibration('alpha', 'mca', 1024, 0, 0, 1000, 6))
        path = Path(self.folder.name, 'calibration.json')
        path.write_bytes(export_item(doc, identity, 'json'))
        self.enter('alpha')
        self.page.locator('[data-page=records]').click()
        self.inspect(path)
        option = self.page.locator('#import-selection option')
        expect(option).to_contain_text(['多道谱仪 · 能量刻度'])
        self.assertNotIn('mca', option.inner_text())
