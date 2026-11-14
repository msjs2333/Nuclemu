"""Compare actual desktop operations and CLI files on one explicit timeline."""
from pathlib import Path
import subprocess
import sys
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.exchange import load_item, load_package
from nuclemu.results import snapshot_product

if fixtures.sync_playwright:
    from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]


def products(document):
    return {i['document']['snapshot']['device']: i['document']
            for i in document['items'] if i['kind'] == 'measurement'}


def observation(product):
    """Ignore local snapshot numbering; compare measured fields verbatim."""
    return dict(exposure_s=product['snapshot']['exposure_s'],
                **{key: product.get(key) for key in ('devices', 'segments', 'windows', 'window_prefix')})


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright for desktop parity')
class CliGuiRoundTripTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def action(self, name, click):
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == name) as response:
            click()
        self.assertTrue(response.value.ok, response.value.text())
        return response.value.json()

    def exposure(self, seconds, beta):
        if beta:
            fixtures.expect_counter_exposure(self.page, seconds)
        else:
            expect(self.page.locator('#exposure')).to_have_text(f'{seconds:g} s')

    def download(self, click, path):
        with self.page.expect_download() as downloading:
            click()
        downloading.value.save_as(path)
        self.assertTrue(path.is_file())

    def run_course(self, name):
        beta = name == 'beta'
        devices = ('counter', 'counter_b') if beta else ('mca',)
        settings = dict(source_present=1, foil_count=0, foil_spec_um=100 if beta else 1)
        out = Path(self.folder.name)
        common = ['run', name, '--seed', '0', '--enable-output', name + '_detector',
                  '--set', 'source_present=1', '--set', f"foil_spec_um={settings['foil_spec_um']}",
                  '--change', '2.5,foil_count=4']
        if beta:
            common += ['--window', 'counter=1', '--window', 'counter_b=5']
        for duration in (3, 5):
            result = subprocess.run([sys.executable, '-m', 'nuclemu', *common, '--duration', str(duration),
                                     '--package', str(out/f'cli-{duration}s.nuclemu')], cwd=ROOT,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
        reference = {n: products(load_package(out/f'cli-{n}s.nuclemu')) for n in (3, 5)}

        self.enter(name)
        self.assertEqual(self.state()['seed'], 0)
        self.page.locator('[name=source_present]').select_option('1')
        self.page.locator('[name=foil_spec_um]').select_option(str(settings['foil_spec_um']))
        self.action('configure', lambda: self.page.get_by_role('button', name='应用参数', exact=True).click())
        self.action('output', lambda: self.page.locator('#output-' + name + '_detector').check())
        self.page.locator('[data-page=instrument]').click()
        if beta:
            self.page.locator('#window-size-counter_b').fill('5')
            self.action('window_config', lambda: self.page.locator('#window-size-counter_b').press('Tab'))
        self.page.locator('#mode').select_option('timed')
        self.page.locator('#duration').fill('5')
        self.action('instrument_group_config' if beta else 'instrument_config',
                    lambda: self.page.locator('#apply-acquisition').click())
        self.action('start_group' if beta else 'start', lambda: self.page.locator('#start').click())
        self.now = 2.5
        self.page.locator('[data-page=setup]').click()
        self.page.locator('[name=foil_count]').fill('4')
        changed = self.action('configure', lambda: self.page.get_by_role('button', name='应用参数', exact=True).click())
        self.assertEqual(changed['time_s'], 2.5)
        self.assertTrue(all(changed['instruments'][d]['running'] for d in devices))
        self.page.locator('[data-page=instrument]').click()
        self.now = 3
        self.exposure(3, beta)
        self.page.locator('#save-current').click()
        self.page.locator('#measurement-name').fill(name + ' three seconds')
        saved = self.action('commit_snapshot_group', lambda: self.page.locator('#measurement-save-confirm').click())
        identity = saved['records'][0]['id']
        self.now = 5
        self.exposure(5, beta)
        expect(self.page.locator('#stop')).to_be_disabled()
        expect(self.page.locator('#start')).to_be_disabled()
        session = self.server.app.lab.work.session
        final = {d: snapshot_product(session.experiment, session.snapshot(d, cache=False), 0) for d in devices}
        for device in devices:
            self.assertEqual(observation(final[device]), observation(reference[5][device]))

        self.page.locator('[data-page=records]').click()
        row = self.page.locator(f'[data-key="r/{identity}"]')
        row.locator('input').check()
        for fmt in ('json', 'csv'):
            row.locator('select').select_option(fmt)
            self.download(lambda: self.page.locator('#export').click(), out/f'gui-3s.{fmt}')
            exported = products(load_item(out/f'gui-3s.{fmt}'))
            for device in devices:
                self.assertEqual(observation(exported[device]), observation(reference[3][device]))
        self.download(lambda: self.page.locator('#download-experiment').click(), out/'gui-whole.nuclemu')
        whole = load_package(out/'gui-whole.nuclemu')
        self.assertEqual(len(whole['items']), len(devices))
        self.assertEqual([r['exposure_s'] for r in whole['rounds']], [5]*len(devices))

    def test_alpha_hot_change_matches_cli_by_channel_and_exposure(self):
        self.run_course('alpha')

    def test_beta_hot_change_matches_cli_by_window_and_exposure(self):
        self.run_course('beta')
