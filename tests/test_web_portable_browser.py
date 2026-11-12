"""Student-visible saved-item downloads and offline .nuclemu reopening."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from zipfile import ZipFile

import test_catalog_records_browser as fixtures
from nuclemu.exchange import load_package
from nuclemu.exchange import bind_calibration, cache_calibration, capture_session, package_bytes, import_item
from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.results import Calibration
from nuclemu.web import make_server

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class PortableWebBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter

    def state(self, page=None, url=None):
        return (page or self.page).request.get((url or self.url) + '/api/state').json()

    def test_saved_spectra_use_their_own_calibration_on_selection_and_comparison(self):
        definition = discover()['alpha']
        documents = []
        for energy in (6, 3):
            session = Session(definition, seed=187)
            session.configure({'source_present': 1})
            session.set_output('alpha_detector', True)
            session.start(3, device='mca')
            session.advance(3)
            session.snapshot('mca')
            doc = capture_session(session)
            cal = cache_calibration(doc, Calibration('alpha', 'mca', 1024, 0, 0, 1000, energy))
            bind_calibration(doc, doc['items'][0]['id'], cal)
            documents.append(doc)
        doc = documents[0]
        other = import_item(doc, documents[1], documents[1]['items'][0]['id'])
        doc['analysis'] = {'mca': {'selected': other, 'reference': doc['items'][0]['id'],
                                  'roi': [845, 875], 'energy_axis': True}}
        path = Path(self.folder.name, 'two-calibrations.nuclemu')
        path.write_bytes(package_bytes(doc))
        self.page.locator('#open-package').set_input_files(path)
        expect(self.page.locator('#plot')).to_be_visible()
        self.page.locator('[data-page=instrument]').click()
        expect(self.page.locator('#peak')).to_contain_text('2.57704 MeV')
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('#sample').select_option(doc['items'][0]['id'])
        self.page.locator('#reference').select_option(other)
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#peak')).to_contain_text('5.15407 MeV')
        self.assertEqual(self.state()['reference_calibration']['energy2'], 3)
        expect(self.page.locator('#legend span')).to_have_count(2)
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('#sample').select_option(other)
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#peak')).to_contain_text('2.57704 MeV')

    def test_spectra_and_saved_calibration_download_and_reopen_offline(self):
        self.enter('alpha')
        self.page.locator('[name=source_present]').select_option('1')
        self.page.get_by_role('button', name='应用参数', exact=True).click()
        self.page.locator('#output-alpha_detector').check()
        self.page.locator('[data-part=mca]').click()
        self.page.locator('#open-instrument').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 3
        expect(self.page.locator('#exposure')).to_have_text('3 s')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#snapshot-notice')).to_have_text('已保存')
        self.assertEqual(len(self.state()['snapshots']), 1)
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('.calibration-tools').evaluate('(el) => el.open = true')
        for name, value in [('c1', 0), ('e1', 0), ('c2', 1000), ('e2', 6)]:
            self.page.locator(f'[name={name}]').fill(str(value))
        self.page.locator('#calibrate button').click()
        expect(self.page.locator('#save-calibration')).to_be_enabled()
        self.page.locator('#save-calibration').click()
        expect(self.page.locator('#calibration-notice')).to_contain_text('刻度已保存')
        self.page.keyboard.press('Escape')
        self.page.get_by_role('tab', name='采集', exact=True).click()
        self.now = 5
        expect(self.page.locator('#exposure')).to_have_text('5 s')
        self.page.locator('#save-current').click()
        self.assertEqual(len(self.state()['snapshots']), 2)
        original = self.state()
        self.now = 7
        expect(self.page.locator('#exposure')).to_have_text('7 s')
        self.page.locator('[data-page=records]').click()
        expect(self.page.locator('#products .product')).to_have_count(3)
        self.page.locator('[data-key="s/1"] input').check()
        self.page.locator('[data-key^="c/"] input').check()
        with self.page.expect_download() as batch:
            self.page.locator('#export').click()
        batch_path = Path(self.folder.name, batch.value.suggested_filename)
        batch.value.save_as(batch_path)
        self.assertRegex(batch.value.suggested_filename, r'^AEL_\d{8}-\d{6}-\d{6}_records\.zip$')
        with ZipFile(batch_path) as selected:
            self.assertEqual(len(selected.namelist()), 2)
            self.assertEqual({Path(name).suffix for name in selected.namelist()}, {'.csv', '.json'})
            calibration_file = Path(self.folder.name, 'saved-calibration.json')
            calibration_file.write_bytes(selected.read(next(name for name in selected.namelist() if name.endswith('.json'))))
        self.page.locator('[data-key^="c/"] input').uncheck()
        with self.page.expect_download() as single_spectrum:
            self.page.locator('#export').click()
        self.assertRegex(single_spectrum.value.suggested_filename,
                         r'^AEL_\d{8}-\d{6}-\d{6}_spectrum\.csv$')
        single_spectrum.value.save_as(Path(self.folder.name, single_spectrum.value.suggested_filename))
        self.page.locator('[data-key="s/1"] input').uncheck()
        self.page.locator('[data-key^="c/"] input').check()
        with self.page.expect_download() as single_calibration:
            self.page.locator('#export').click()
        self.assertRegex(single_calibration.value.suggested_filename,
                         r'^AEL_\d{8}-\d{6}-\d{6}_calibration\.json$')
        single_calibration.value.save_as(Path(self.folder.name, single_calibration.value.suggested_filename))
        self.page.locator('[data-page=instrument]').click()
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('.calibration-tools').evaluate('(el) => el.open = true')
        self.page.locator('#calibrate [name=e2]').fill('5.9')
        self.page.locator('#calibrate button').click()
        self.page.wait_for_function("document.querySelector('#calibrate [name=e2]').value === '5.9'")
        with self.page.expect_file_chooser() as chooser:
            self.page.locator('#load-calibration').click()
        chooser.value.set_files(calibration_file)
        self.page.wait_for_function("document.querySelector('#calibrate [name=e2]').value === '6'")
        self.assertEqual(self.state()['calibration']['energy2'], 6)
        self.page.keyboard.press('Escape')
        self.page.locator('[data-page=records]').click()
        with self.page.expect_download() as package:
            self.page.locator('#download-experiment').click()
        package_path = Path(self.folder.name, package.value.suggested_filename)
        package.value.save_as(package_path)
        self.assertTrue(package_path.name.endswith('.nuclemu'))
        self.assertRegex(package_path.name, r'^AEL_\d{8}-\d{6}-\d{6}\.nuclemu$')
        with ZipFile(package_path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['format'], 'nuclemu.package/1')
            with closing(sqlite3.connect(':memory:')) as db:
                db.deserialize(archive.read('experiment.sqlite3'))
                self.assertEqual(db.execute('select count(*) from items').fetchone()[0], 3)
        doc = load_package(package_path)
        measurements = [item for item in doc['items'] if item['kind'] == 'measurement']
        self.assertEqual([m['document']['snapshot']['exposure_s'] for m in measurements], [3, 5])
        self.assertEqual(len({m['document']['snapshot']['acquisition'] for m in measurements}), 1)
        self.assertEqual(len({m['calibration_id'] for m in measurements}), 1)
        self.assertTrue(self.state()['running'])
        self.page.locator('#menu-file').click()
        with self.page.expect_download() as same_command:
            self.page.locator('#save').click()
        self.assertTrue(same_command.value.suggested_filename.endswith('.nuclemu'))
        self.assertRegex(same_command.value.suggested_filename, r'^AEL_\d{8}-\d{6}-\d{6}\.nuclemu$')
        self.assertEqual(self.state()['snapshots'], original['snapshots'])
        self.assertEqual(self.server.app.catalog()['archives'], [])
        self.assertEqual(self.server.app.catalog()['drafts'], [])

        with TemporaryDirectory() as offline, make_server(directory=offline, clock=lambda: self.now) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            page = self.browser.new_page()
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                page.goto(url)
                page.locator('#open-package').set_input_files(package_path)
                expect(page.locator('#portable-view')).to_be_visible()
                restored = self.state(page, url)
                self.assertEqual([s['exposure_s'] for s in restored['snapshots']], [3, 5])
                self.assertEqual(restored['readout']['counts'], original['snapshots'][1]['counts'])
                self.assertEqual(restored['readout']['exposure_s'], 5)
                self.assertEqual(restored['instrument']['exposure_s'], 0)
                self.assertIsNotNone(restored['calibration'])
                self.assertEqual(restored['cached_calibrations'], original['cached_calibrations'])
                page.locator('[data-page=setup]').click()
                page.locator('#output-alpha_detector').check()
                page.locator('[data-part=mca]').click()
                page.locator('#open-instrument').click()
                page.locator('#start').click()
                expect(page.locator('#stop')).to_be_enabled()
                self.now += 1
                expect(page.locator('#exposure')).to_have_text('1 s')
                final = self.state(page, url)
                self.assertEqual(final['instrument']['acquisition'], 2)
                self.assertEqual(final['snapshots'], restored['snapshots'])
            finally:
                page.close()
                server.shutdown()
                worker.join()
        before_import = self.state()
        native_snapshots = tuple(self.server.app.lab.work.session.snapshots)
        imported_ids = []
        for _ in range(2):
            self.page.locator('[data-page=records]').click()
            with self.page.expect_file_chooser() as choice:
                self.page.locator('#choose-import').click()
            choice.value.set_files(package_path)
            expect(self.page.locator('#import-choice')).to_be_visible()
            self.page.locator('#import-selection').select_option(measurements[0]['id'])
            with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'import_item') as applied:
                self.page.locator('#confirm-import').click()
            self.assertTrue(applied.value.ok, applied.value.text())
            self.assertIn('product', applied.value.json())
            expect(self.page.locator('#import-choice')).not_to_be_visible()
            current = self.state()
            imported_ids.append(current['imported_items'][-1]['id'])
            self.assertNotEqual(imported_ids[-1], measurements[0]['id'])
            self.assertEqual(current['instrument'], before_import['instrument'])
            self.assertEqual(tuple(self.server.app.lab.work.session.snapshots), native_snapshots)
            self.assertEqual(current['analysis']['reference'], before_import['analysis']['reference'])
        self.assertNotEqual(imported_ids[0], imported_ids[1])
        self.page.locator('[data-page=instrument]').click()
        self.page.get_by_role('tab', name='谱分析', exact=True).click()
        self.page.locator('#reference').select_option(imported_ids[-1])
        self.page.keyboard.press('Escape')
        self.page.locator('[data-page=records]').click()
        with self.page.expect_download() as with_imports:
            self.page.locator('#download-experiment').click()
        imported_path = Path(self.folder.name, 'with-imports.nuclemu')
        with_imports.value.save_as(imported_path)
        imported_package = load_package(imported_path)
        self.assertEqual(imported_package['analysis']['mca']['reference'], imported_ids[-1])
        imported_item = next(item for item in imported_package['items'] if item['id'] == imported_ids[-1])
        self.assertEqual(imported_item['source']['package'], doc['id'])

    def test_exit_download_failure_or_cancellation_keeps_live_cache(self):
        self.enter('alpha')
        self.page.locator('[name=source_present]').select_option('1')
        self.page.get_by_role('button', name='应用参数', exact=True).click()
        self.page.locator('#output-alpha_detector').check()
        self.page.locator('[data-part=mca]').click()
        self.page.locator('#open-instrument').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1
        expect(self.page.locator('#exposure')).to_have_text('1 s')
        self.page.locator('#save-current').click()
        expect(self.page.locator('#snapshot-notice')).to_have_text('已保存')
        self.assertEqual(len(self.state()['snapshots']), 1)
        original = self.state()
        self.page.reload()
        expect(self.page.locator('#plot')).to_be_visible()
        self.assertEqual(len(self.state()['snapshots']), 1)
        self.assertEqual(self.state()['id'], original['id'])
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        expect(self.page.locator('#confirm')).to_be_visible()
        self.page.route('**/api/download', lambda route: route.fulfill(status=500, json={'error': 'controlled download failure'}))
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#exit-error')).to_contain_text('controlled download failure')
        self.assertEqual(self.state()['snapshots'], original['snapshots'])
        self.page.unroute('**/api/download')
        with self.page.expect_download() as pending:
            self.page.locator('#save-exit').click()
        pending.value.cancel()
        self.assertRegex(pending.value.suggested_filename, r'^AEL_\d{8}-\d{6}-\d{6}\.nuclemu$')
        expect(self.page.locator('#exit-download-status')).to_contain_text('已发起下载')
        expect(self.page.locator('#confirm')).to_be_visible()
        self.page.locator('#cancel').click()
        expect(self.page.locator('#confirm')).not_to_be_visible()
        self.assertTrue(self.state()['running'])
        self.assertEqual(self.state()['snapshots'], original['snapshots'])
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        self.page.locator('#discard').click()
        expect(self.page.locator('#catalog')).to_be_visible()
        self.assertIsNone(self.state())
        self.assertEqual(self.server.app.catalog()['archives'], [])
        self.assertEqual(self.server.app.catalog()['drafts'], [])

    def test_invalid_experiment_replacement_can_return_to_the_original_session(self):
        self.enter('alpha')
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now = 1
        expect(self.page.locator('#exposure')).to_have_text('1 s')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'snapshot') as saved:
            self.page.locator('#save-current').click()
        self.assertTrue(saved.value.ok)
        original = self.state()
        invalid = Path(self.folder.name, 'invalid.nuclemu')
        invalid.write_bytes(b'invalid experiment')
        self.page.locator('#menu-file').click()
        with self.page.expect_file_chooser() as choice:
            self.page.locator('#load-experiment').click()
        choice.value.set_files(invalid)
        expect(self.page.locator('#confirm')).to_be_visible()
        self.page.locator('#discard').click()
        expect(self.page.locator('#exit-error')).not_to_be_empty()
        self.assertEqual(self.state()['id'], original['id'])
        self.assertEqual(self.state()['snapshots'], original['snapshots'])
        self.page.locator('#cancel').click()
        expect(self.page.locator('#confirm')).not_to_be_visible()
        self.assertTrue(self.state()['running'])


if __name__ == '__main__':
    unittest.main()
