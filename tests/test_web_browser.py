"""Optional browser regression for a course supplied through --path."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from nuclemu.web import make_server

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


EXTERNAL = """
from nuclemu.core import Device, Experiment, Parameter

def readings(settings, start, end, rng):
    return {"left": [1], "right": [9]}

EXPERIMENT = Experiment("parallel", "双计数器", "同时读取两台仪器",
    (Parameter("foil", "箔片", "", 0, 0, 8, True),),
    (Device("left", "counter", "左计数器"), Device("right", "counter", "右计数器")),
    readings)
"""


@unittest.skipUnless(sync_playwright, "Install Playwright and Chromium to run the browser test")
class BrowserPluginTests(unittest.TestCase):
    def test_two_external_instruments_keep_distinct_readings_after_reopening(self):
        with TemporaryDirectory() as folder, sync_playwright() as playwright:
            executable = Path(os.environ.get("NUCLEMU_TEST_BROWSER", playwright.chromium.executable_path))
            if not executable.is_file():
                self.skipTest("Install Playwright Chromium or set NUCLEMU_TEST_BROWSER to a Chromium browser")
            Path(folder, "parallel.py").write_text(EXTERNAL, encoding="utf-8")
            now = 0.0
            with make_server([folder], directory=folder, clock=lambda: now) as server:
                worker = Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
                worker.start()
                try:
                    with playwright.chromium.launch(executable_path=executable) as browser:
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_port}")
                        course = page.locator("article").filter(has_text="双计数器")
                        course.get_by_role("button", name="进入实验").click()
                        expect(page.locator("header h1")).to_have_text("双计数器")
                        expect(page.get_by_text("A Virtual Nuclear Physics Lab", exact=True)).to_have_count(0)
                        instrument = page.locator('[data-part]').filter(has_text='右计数器')
                        instrument.focus()
                        instrument.press("Enter")
                        expect(page.locator('#component h2')).to_have_text('右计数器')
                        page.locator('#open-instrument').focus()
                        page.locator('#open-instrument').press('Enter')
                        expect(page.locator("#device")).to_have_value("right")
                        expect(page.locator("#device")).to_be_focused()
                        expect(page.locator("#duration")).to_be_visible()
                        page.locator('#mode').select_option('timed')
                        page.locator("#duration").fill("1")
                        page.keyboard.press("Escape")
                        # Menu keyboard dismissal remains available independently of acquisition.
                        page.locator("#menu-simulation").click()
                        page.keyboard.press("Escape")
                        expect(page.locator("#menu-simulation")).to_be_focused()
                        page.locator("#start").click()
                        expect(page.locator("#gate-status")).to_have_text("采集中")
                        now = 1
                        expect(page.locator("#counts tr td").nth(1)).to_have_text("9")
                        page.locator("#device").select_option("left")
                        expect(page.locator("#counts tr td").nth(1)).to_have_text("1")
                        page.locator("#menu-file").click()
                        page.locator("#leave").click()
                        with page.expect_response(lambda r: r.url.endswith('/api/action') and r.request.post_data_json.get('action') == 'save') as saved:
                            page.locator("#save-exit").click()
                        self.assertTrue(saved.value.ok, saved.value.text())
                        expect(page.locator('#catalog')).to_be_visible()
                        # Old archives remain explicitly readable without appearing on the catalogue.
                        expect(page.locator(".archive-table")).to_have_count(0)
                        archives = server.app.catalog()["archives"]
                        self.assertEqual(len(archives), 1)
                        response = page.request.post(f"http://127.0.0.1:{server.server_port}/api/open",
                                                     data={"archive": archives[0]["id"]})
                        self.assertTrue(response.ok, response.text())
                        self.assertTrue(response.json()["readonly"])
                        page.goto(f"http://127.0.0.1:{server.server_port}/lab/parallel/#instrument")
                        expect(page.locator("#device")).to_have_value("left")
                        expect(page.locator("#counts tr td").nth(1)).to_have_text("1")
                        page.locator("#device").select_option("right")
                        expect(page.locator("#counts tr td").nth(1)).to_have_text("9")
                        expect(page.locator("#start")).to_be_disabled()
                finally:
                    server.shutdown()
                    worker.join()
