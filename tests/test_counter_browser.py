"""Desktop counter workflows: generic courses, raw counts and dual-window changes."""

import json
import math
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.results import net_count_rate

try:
    from playwright.sync_api import expect
except ImportError:
    expect = None


ZERO_COURSE = '''
from nuclemu.core import Component, Device, Experiment, Parameter

def count(settings, start, end, rng):
    return {'meter': [3 if settings['mode'] == 5 else 0]}
EXPERIMENT = Experiment('zero-counter', '零计数实验', '检查整数计数与曝光',
    (Parameter('mode', '源模式', '', 5, 0, 5, True, options=((5,'测本底'),(0,'测样品'))),),
    (Device('meter','counter','计数器',background_conditions={'mode':5}),), count,
    components=(Component('holder','source','源座',parameters=('mode',)),
                Component('meter','instrument','计数器',device='meter')))
'''


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class CounterBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot
    enter = fixtures.CatalogRecordsBrowserTests.enter
    collect = fixtures.CatalogRecordsBrowserTests.collect

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def configure(self, key, value):
        self.page.locator('[data-page=setup]').click()
        self.page.locator('#operation-tab').click()
        field = self.page.locator(f'[name="{key}"]')
        if field.input_value() == str(value):
            self.page.locator('[data-page=instrument]').click()
            return
        if field.evaluate('(e) => e.tagName') == 'SELECT':
            field.select_option(str(value))
        else:
            field.fill(str(value))
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'configure') as result:
            self.page.locator('#operation-panel form button').click()
        self.assertTrue(result.value.ok, result.value.text())
        expect(field).to_have_value(str(value))
        self.page.locator('[data-page=instrument]').click()

    def raw_rows(self):
        return self.page.locator('#counts tbody tr')

    def export_row(self, device, index):
        self.page.locator('[data-page=records]').click()
        row = self.page.locator(f'#products .product[data-device="{device}"][data-index="{index}"]')
        row.locator('input[type=checkbox]').check()
        row.locator('select').select_option('json')
        with self.page.expect_download() as download:
            self.page.locator('#export').click()
        path = Path(self.folder.name, f'{device}-{index}.json')
        download.value.save_as(path)
        row.locator('input[type=checkbox]').uncheck()
        return json.loads(path.read_text(encoding='utf-8'))

    def test_legacy_beta_raw_measurements_and_readonly_archive(self):
        self.enter(fixtures.install_legacy(self, 'beta'))
        # Parameters are available without selecting a source part first.
        expect(self.page.locator('[name=source_present]')).to_be_visible()
        self.configure('source_present', 0)
        self.collect(2.5)
        self.configure('source_present', 1)
        self.collect(4.25)
        self.configure('source_present', 0)
        self.collect(1.25)
        expect(self.raw_rows()).to_have_count(3)
        expect(self.page.locator('#background, #counter-analysis')).to_have_count(0)
        product = self.state()['product']
        bg, sample, other_bg = product['segments']
        self.assertEqual([s['settings']['source_present'] for s in product['segments']], [0, 1, 0])
        self.assertEqual([s['end_s']-s['start_s'] for s in product['segments']], [2.5, 4.25, 1.25])
        exported = self.export_row('counter', 1)
        self.assertEqual(exported['segments'], [sample])
        # Analysis is performed outside the student workbench using the raw values.
        ns, nb = sample['readings']['counter'][0], bg['readings']['counter'][0]
        net, error = net_count_rate(ns, 4.25, nb, 2.5)
        self.assertAlmostEqual(net, ns/4.25-nb/2.5)
        self.assertAlmostEqual(error, math.sqrt(ns/4.25**2+nb/2.5**2))
        self.assertNotEqual(bg['acquisition'], other_bg['acquisition'])
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        self.page.locator('#save-exit').click()
        expect(self.page.locator('#catalog')).to_be_visible()
        # The homepage no longer enumerates old archives; the explicit legacy
        # fixture helper opens the public read-only archive protocol.
        fixtures.open_legacy_archive(self)
        expect(self.page.locator('#start')).to_be_disabled()
        expect(self.raw_rows()).to_have_count(3)
        self.assertEqual(self.state()['product'], product)
        self.page.locator('[data-page=setup]').click()
        expect(self.page.locator('[name=source_present]')).to_be_disabled()

    def test_external_two_counters_keep_raw_device_readings_and_exports(self):
        self.enter('records-test')
        self.collect(1.25)
        self.collect(.75)
        self.page.locator('#device').select_option('left')
        expect(self.raw_rows().first.locator('td').nth(1)).to_have_text('4')
        expect(self.page.locator('#background')).to_have_count(0)
        left = self.export_row('left', 0)['segments'][0]
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#device').select_option('right')
        expect(self.raw_rows().first.locator('td').nth(1)).to_have_text('14')
        right = self.export_row('right', 1)['segments'][0]
        self.assertEqual(left['readings'], {'left': [4]})
        self.assertEqual(right['readings'], {'right': [7]})
        self.assertEqual((left['end_s']-left['start_s'], right['end_s']-right['start_s']), (1.25, .75))
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#device').select_option('left')
        expect(self.raw_rows().first.locator('td').nth(1)).to_have_text('4')
        self.assertEqual([s['readings'] for s in self.state()['product']['segments']],
                         [{'left': [4], 'right': [14]}, {'left': [2], 'right': [7]}])

    def test_source_change_during_acquisition_preserves_both_gates_and_window_parts(self):
        self.enter('beta')
        self.configure('source_present', 0)
        fixtures.enable_output(self)
        for device in ('counter', 'counter_b'):
            with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                           r.request.post_data_json.get('action') == 'window_config') as changed:
                self.page.locator(f'#window-size-{device}').fill('1.5')
                self.page.locator(f'#window-size-{device}').press('Tab')
            self.assertTrue(changed.value.ok, changed.value.text())
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('1.5')
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'start_group') as started:
            self.page.locator('#start').click()
        self.assertTrue(started.value.ok, started.value.text())
        self.assertEqual(self.state()['gates'], {'counter': True, 'counter_b': True})
        self.now = .25
        self.configure('source_present', 1)
        self.assertEqual(self.state()['gates'], {'counter': True, 'counter_b': True})
        self.now = 1.5
        expect(self.page.locator('#stop')).to_be_disabled()
        expect(self.page.locator('.counter-window')).to_have_count(2)
        for panel in self.page.locator('.counter-window').all():
            expect(panel.locator('tbody tr')).to_have_count(1)
        state = self.state()
        for device in ('counter', 'counter_b'):
            window, = state['counter_windows'][device]
            self.assertEqual((window['start_exposure_s'], window['end_exposure_s']), (0, 1.5))
            self.assertEqual([p['settings']['source_present'] for p in window['parts']], [0, 1, 1])
            self.assertEqual([(p['start_s'], p['end_s']) for p in window['parts']], [(0, .25), (.25, 1), (1, 1.5)])
            self.assertEqual(sum(p['readings'][device][0] for p in window['parts']), window['counts'][0])
        expect(self.page.locator('#background, #counter-analysis')).to_have_count(0)

    def test_external_zero_count_is_exported_and_negative_net_is_calculated_locally(self):
        Path(self.folder.name, 'zero.py').write_text(ZERO_COURSE, encoding='utf-8')
        from nuclemu.catalog import discover
        self.server.app.definitions = discover([self.folder.name])
        self.page.reload()
        self.enter('zero-counter')
        expect(self.page.locator('[name=mode]')).to_have_value('5')
        self.collect(1)
        self.configure('mode', 0)
        self.collect(1)
        expect(self.raw_rows().nth(1).locator('td').nth(1)).to_have_text('0')
        expect(self.raw_rows().nth(1).locator('td').nth(2)).to_have_text('1')
        sample = self.export_row('meter', 1)['segments'][0]
        self.assertEqual((sample['readings']['meter'], sample['end_s']-sample['start_s']), ([0], 1))
        self.assertEqual(net_count_rate(0, 1, 3, 1), (-3, math.sqrt(3)))
        self.page.locator('[data-page=instrument]').click()
        expect(self.page.locator('#background, #counter-analysis')).to_have_count(0)
        self.screenshot('counter-zero-raw')

    def test_shared_source_for_external_counters_keeps_generic_editor_and_bindings(self):
        from dataclasses import replace
        from nuclemu.catalog import discover
        from nuclemu.core import Component, Device
        Path(self.folder.name, 'zero.py').write_text(ZERO_COURSE, encoding='utf-8')
        definitions = discover([self.folder.name])
        old = definitions['zero-counter']
        definitions['zero-counter'] = replace(old, devices=(*old.devices,
            Device('second', 'counter', '第二计数器', background_conditions={'mode': 5})),
            components=(*old.components, Component('second', 'instrument', '第二计数器', device='second')),
            model=lambda settings, start, end, rng: {'meter': (3,), 'second': (4,)})
        self.server.app.definitions = definitions
        self.page.reload()
        self.enter('zero-counter')
        expect(self.page.locator('[name=mode]')).to_be_visible()
        self.configure('mode', 0)
        self.collect(1)
        self.page.locator('#device').select_option('second')
        expect(self.raw_rows().first.locator('td').nth(1)).to_have_text('4')
        self.page.locator('#device').select_option('meter')
        expect(self.raw_rows().first.locator('td').nth(1)).to_have_text('3')
        self.assertEqual(self.state()['product']['segments'][0]['settings']['mode'], 0)
