"""Optional isolated-browser checks for the counter bench and its reference selection."""

import math
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures

try:
    from playwright.sync_api import expect
except ImportError:
    expect = None


ZERO_COURSE = '''
from nuclemu.core import Component, Device, Experiment, Parameter
def count(settings, start, end, rng):
    return {'meter': [3 if settings['mode'] == 5 else 0]}
EXPERIMENT = Experiment('zero-counter', '零计数实验', '检查负净率',
    (Parameter('mode', '源模式', '', 5, 0, 5, True, options=((5,'测本底'),(0,'测样品'))),),
    (Device('meter','counter','计数器',background_conditions={'mode':5}),), count,
    components=(Component('holder','source','源座',parameters=('mode',)),
                Component('meter','instrument','计数器',device='meter')))
'''


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run browser checks')
class CounterBrowserTests(unittest.TestCase):
    # Reuse isolated-server helpers without inheriting unrelated catalogue scenarios.
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot
    enter = fixtures.CatalogRecordsBrowserTests.enter
    collect = fixtures.CatalogRecordsBrowserTests.collect

    def net_cells(self, index):
        return self.page.locator('#counts tr').nth(index).locator('td').last

    def test_beta_source_navigation_multiple_backgrounds_and_readonly_archive(self):
        self.enter('beta')
        expect(self.page.locator('[name="source_present"]')).to_have_count(0)
        self.page.get_by_role('button', name='在计数器选择测量模式').click()
        expect(self.page.locator('#counter')).to_be_visible()
        expect(self.page.locator('#background')).to_have_count(1)
        self.page.get_by_role('button', name='本底', exact=True).click()
        self.collect(2.5)
        self.page.get_by_role('button', name='有源', exact=True).click()
        self.collect(4.25)
        self.page.get_by_role('button', name='本底', exact=True).click()
        self.collect(1.25)
        expect(self.page.locator('#background option')).to_have_count(3)
        self.page.locator('#background').select_option('0')
        expect(self.net_cells(0)).to_have_text('本底参考')
        expect(self.net_cells(2)).to_have_text('—')
        product = self.page.request.get(self.url + '/api/state').json()['product']
        bg, sample, _ = product['segments']
        nb, ns = bg['readings']['counter'][0], sample['readings']['counter'][0]
        net, error = ns / 4.25 - nb / 2.5, math.sqrt(ns / 4.25**2 + nb / 2.5**2)
        text = self.net_cells(1).inner_text()
        actual = [float(v.replace(',', '')) for v in text.split(' ± ')]
        self.assertAlmostEqual(actual[0], net, delta=.00051)
        self.assertAlmostEqual(actual[1], error, delta=.00051)
        expect(self.page.locator('#counts tr').nth(1).locator('td').nth(3)).to_have_text('4.25')
        self.screenshot('beta-counter-desktop')
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.assertTrue(self.page.locator('.counter-ledger').evaluate('e => e.scrollWidth > e.clientWidth'))
        expect(self.page.locator('#background')).to_be_visible()
        self.screenshot('beta-counter-390')
        self.page.locator('#menu-file').click()
        self.page.locator('#leave').click()
        self.page.locator('#save-exit').click()
        self.page.get_by_role('button', name='查看实验', exact=True).click()
        self.page.locator('[data-page="instrument"]').click()
        expect(self.page.locator('#start')).to_be_disabled()
        expect(self.page.get_by_role('button', name='有源', exact=True)).to_be_disabled()
        expect(self.page.locator('#background')).to_have_value('0')
        expect(self.net_cells(1)).to_have_text(text)
        self.page.locator('#background').select_option('2')
        expect(self.net_cells(2)).to_have_text('本底参考')

    def test_two_counters_keep_independent_reference_choices_and_counts(self):
        self.enter('records-test')
        self.collect(1.25)
        self.collect(.75)
        expect(self.page.locator('.counter-mode')).to_have_count(0)
        self.page.locator('#device').select_option('left')
        self.page.locator('#background').select_option('0')
        expect(self.page.locator('#counts tr').nth(0).locator('td').nth(3)).to_have_text('4')
        expect(self.net_cells(1)).to_have_text('-0.533 ± 2.473')
        self.page.locator('#device').select_option('right')
        expect(self.page.locator('#background')).to_have_value('')
        expect(self.page.locator('#counts tr').nth(0).locator('td').nth(3)).to_have_text('14')
        self.page.locator('#background').select_option('1')
        expect(self.net_cells(1)).to_have_text('所选参考')
        self.page.locator('#device').select_option('left')
        expect(self.page.locator('#background')).to_have_value('0')

    def test_source_change_during_acquisition_splits_exposure_without_stopping_gate(self):
        self.enter('beta')
        self.page.get_by_role('button', name='在计数器选择测量模式').click()
        self.page.get_by_role('button', name='本底', exact=True).click()
        self.page.locator('#menu-acquisition').click()
        self.page.locator('#duration').fill('1.5')
        self.page.keyboard.press('Escape')
        self.page.locator('#start').click()
        expect(self.page.locator('#gate-status')).to_have_text('采集中')
        self.now = .25
        expect(self.page.get_by_role('button', name='有源', exact=True)).to_be_enabled()
        self.page.get_by_role('button', name='有源', exact=True).click()
        expect(self.page.locator('#counts tr')).to_have_count(1)
        expect(self.page.locator('#gate-status')).to_have_text('采集中')
        self.now = 1.5
        expect(self.page.locator('#gate-status')).to_have_text('采集门关闭')
        expect(self.page.locator('#counts tr')).to_have_count(2)
        product = self.page.request.get(self.url + '/api/state').json()['product']
        first, second = product['segments']
        self.assertEqual((first['acquisition'], second['acquisition']), (1, 1))
        self.assertEqual((first['start_s'], first['end_s'], second['start_s'], second['end_s']),
                         (0, .25, .25, 1.5))
        self.assertEqual((first['settings']['source_present'], second['settings']['source_present']), (0, 1))
        self.page.locator('#background').select_option('0')
        expect(self.net_cells(1)).to_contain_text(' ± ')

    def test_nonzero_background_rule_zero_counts_and_negative_net(self):
        # Restart catalogue discovery with one additional trusted test module.
        Path(self.folder.name, 'zero.py').write_text(ZERO_COURSE, encoding='utf-8')
        from nuclemu.catalog import discover
        self.server.app.definitions = discover([self.folder.name])
        self.page.reload()
        self.enter('zero-counter')
        self.page.get_by_role('button', name='在计数器选择源模式').click()
        self.collect(1)
        self.page.get_by_role('button', name='测样品', exact=True).click()
        self.collect(1)
        self.page.locator('#background').select_option('0')
        expect(self.page.locator('#counts tr').nth(1).locator('td').nth(3)).to_have_text('0')
        expect(self.net_cells(1)).to_have_text('-3 ± 1.732')
        self.screenshot('counter-zero-negative')

    def test_shared_source_for_two_counters_keeps_the_generic_editor(self):
        from dataclasses import replace
        from nuclemu.catalog import discover
        from nuclemu.core import Component, Device

        Path(self.folder.name, 'zero.py').write_text(ZERO_COURSE, encoding='utf-8')
        definitions = discover([self.folder.name])
        old = definitions['zero-counter']
        def count(settings, start, end, rng):
            return {'meter': (3,), 'second': (4,)}
        definitions['zero-counter'] = replace(old, devices=(*old.devices,
            Device('second', 'counter', '第二计数器', background_conditions={'mode': 5})),
            components=(*old.components, Component('second', 'instrument', '第二计数器', device='second')),
            model=count)
        self.server.app.definitions = definitions
        self.page.reload()
        self.enter('zero-counter')
        expect(self.page.locator('[name="mode"]')).to_be_visible()
        expect(self.page.get_by_role('button', name='在计数器选择源模式')).to_have_count(0)
        self.collect(1)
        expect(self.page.locator('.counter-mode')).to_have_count(0)
        self.page.locator('#device').select_option('second')
        expect(self.page.locator('#counts tr').locator('td').nth(3)).to_have_text('4')
