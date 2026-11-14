"""Physical counter bindings remain stable when course devices are reordered."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.core import Component, Device, Experiment, SignalOutput
from nuclemu.exchange import load_item, load_package
from nuclemu.web import make_server

if fixtures.sync_playwright:
    from playwright.sync_api import expect

DETECTOR_OUTPUT = 'identity-pulses'


def ordered_counter_course():
    # A known common input checks device identity rather than random equality.
    def pulses(settings, start, end, rng):
        return {DETECTOR_OUTPUT: (round(10 * (end - start)),)}

    solo = Device('solo', 'counter', '计数窗', input=DETECTOR_OUTPUT)
    return Experiment('counter-ordering', '计数器绑定顺序核对', '恒定脉冲输入的设备绑定核对', (),
        (Device('counter_b', 'counter', '计数窗', input=DETECTOR_OUTPUT), solo,
         Device('counter', 'counter', '计数窗', input=DETECTOR_OUTPUT)), pulses,
        outputs=(SignalOutput(DETECTOR_OUTPUT, '恒定脉冲输出'),), short_code='ORDER',
        components=(Component('input', 'detector', '脉冲输入', output=DETECTOR_OUTPUT),
                    Component('counter', 'instrument', '双窗计数器', device='counter', devices=('counter', 'counter_b')),
                    Component('solo-instrument', 'instrument', '独立计数器', device='solo')))


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class CounterIdentityBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def action(self, action, click):
        with self.page.expect_response(lambda response: response.url.endswith('/api/action') and
                                       response.request.post_data_json.get('action') == action) as result:
            click()
        self.assertTrue(result.value.ok, result.value.text())
        return result.value.json()

    def test_reversed_devices_keep_panel_target_record_and_download_identity(self):
        course = ordered_counter_course()
        self.server.app.definitions[course.id] = course
        self.page.reload()
        self.enter(course.id)
        self.page.locator('#output-' + DETECTOR_OUTPUT).check()
        self.page.locator('[data-part=counter]').click()
        self.page.locator('#open-instrument').click()
        panels = self.page.locator('.counter-window')
        expect(panels).to_have_count(2)
        self.assertEqual(panels.nth(0).get_by_role('spinbutton').get_attribute('id'), 'window-size-counter')
        self.assertEqual(panels.nth(1).get_by_role('spinbutton').get_attribute('id'), 'window-size-counter_b')
        expect(panels.nth(0).locator('h2')).to_have_text('窗 A')
        expect(panels.nth(1).locator('h2')).to_have_text('窗 B')
        expect(self.page.locator('#device')).to_have_count(0)
        self.page.locator('#window-size-counter_b').fill('5')
        self.action('window_config', lambda: self.page.locator('#window-size-counter_b').press('Tab'))
        self.action('start_group', lambda: self.page.locator('#start').click())
        self.now = 5
        expect(panels.nth(0).locator('tbody tr')).to_have_count(5)
        expect(panels.nth(1).locator('tbody tr')).to_have_count(1)
        expect(panels.nth(0).locator('.window-reading strong')).to_have_text('10')
        expect(panels.nth(1).locator('.window-reading strong')).to_have_text('50')
        self.screenshot('counter-reversed-panels')
        for device in ('counter', 'counter_b'):
            self.action('snapshot', lambda: fixtures.measurement_operation(self.page, 'save', device))
        self.page.locator('[data-instrument=solo-instrument]').click()
        expect(panels).to_have_count(1)
        expect(panels.locator('h2')).to_have_text('独立计数器')
        expect(self.page.locator('#window-size')).to_be_visible()
        self.action('start', lambda: self.page.locator('#start').click())
        self.now = 6
        expect(panels.locator('.window-reading strong')).to_have_text('10')
        self.action('stop', lambda: self.page.locator('#stop').click())
        self.now = 7
        state = self.state()
        self.assertEqual({key: value['exposure_s'] for key, value in state['instruments'].items()},
                         {'counter_b': 7, 'solo': 1, 'counter': 7})
        self.assertTrue(state['gates']['counter'])
        self.assertTrue(state['gates']['counter_b'])
        self.assertFalse(state['gates']['solo'])
        self.screenshot('counter-independent-panel')
        self.action('snapshot', lambda: self.page.locator('#save-current').click())
        self.page.locator('[data-page=records]').click()
        expect(self.page.locator('#products .product')).to_have_count(3)
        expected = {'counter': ('双窗计数器 · 窗 A', 'counts-A', 5),
                    'counter_b': ('双窗计数器 · 窗 B', 'counts-B', 5),
                    'solo': ('独立计数器', 'counts-solo', 1)}
        evidence = {}
        for device, (label, suffix, exposure) in expected.items():
            row = self.page.locator(f'#products [data-device="{device}"]')
            expect(row.locator('.product-device')).to_have_text(label)
            row.locator('input').check()
            with self.page.expect_download() as download:
                self.page.locator('#export').click()
            self.assertTrue(download.value.suggested_filename.endswith('_' + suffix + '.csv'))
            path = Path(self.folder.name, download.value.suggested_filename)
            download.value.save_as(path)
            if os.environ.get('NUCLEMU_REVIEW_OUTPUT'):
                directory = Path(os.environ['NUCLEMU_REVIEW_OUTPUT'])
                directory.mkdir(parents=True, exist_ok=True)
                (directory / path.name).write_bytes(path.read_bytes())
            document = load_item(path.read_bytes())['items'][0]['document']
            self.assertEqual(document['snapshot']['device'], device)
            self.assertEqual(document['snapshot']['exposure_s'], exposure)
            evidence[device] = dict(label=label, filename=download.value.suggested_filename,
                                    snapshot=document['snapshot'])
            row.locator('input').uncheck()
        with self.page.expect_download() as package:
            self.page.locator('#download-experiment').click()
        path = Path(self.folder.name, package.value.suggested_filename)
        package.value.save_as(path)
        document = load_package(path)
        self.assertEqual({item['document']['snapshot']['device'] for item in document['items']
                          if item['kind'] == 'measurement'}, set(expected))
        output = os.environ.get('NUCLEMU_REVIEW_OUTPUT')
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=directory / 'counter-record-identities.png', full_page=True)
            (directory / 'counter-identities.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            (directory / path.name).write_bytes(path.read_bytes())
        with TemporaryDirectory() as folder, make_server(directory=folder, clock=lambda: self.now) as server:
            server.app.definitions[course.id] = course
            worker = Thread(target=server.serve_forever)
            worker.start()
            page = self.browser.new_page(viewport={'width': 1366, 'height': 768})
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('#open-package').set_input_files(path)
                expect(page.locator('#device')).to_have_value('solo')
                expect(page.locator('.counter-window')).to_have_count(1)
                page.locator('#device').select_option('counter')
                expect(page.locator('.counter-window h2')).to_have_text(['窗 A', '窗 B'])
                page.locator('[data-page=records]').click()
                expect(page.locator('#products .product-device')).to_have_text(list(label for label, _, _ in expected.values()))
            finally:
                page.close()
                server.shutdown()
                worker.join()
