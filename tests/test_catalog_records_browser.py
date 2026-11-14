"""Optional browser checks for the catalogue and selectable experiment records."""

import csv
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from zipfile import ZipFile

from nuclemu.web import make_server
from legacy_web_fixture import legacy_course

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


EXTERNAL = """
from nuclemu.core import Device, Experiment, Parameter
def measure(settings, start, end, rng):
    return {'left': [2], 'right': [7]}
EXPERIMENT = Experiment('records-test', '双仪器记录', '比较两台计数器的测量。',
    (Parameter('foil', '箔片数', '片', 0, 0, 8, True),),
    (Device('left', 'counter', '计数器'), Device('right', 'counter', '计数器')), measure)
"""


def install_legacy(test, name):
    """Inject only the explicit archived/draft scenario into the public old protocol."""
    definition = legacy_course(name)
    test.server.app.definitions[definition.id] = definition
    test.page.reload()
    return definition.id


def open_legacy_archive(test):
    archives = test.server.app.catalog()["archives"]
    test.assertTrue(archives)
    response = test.page.request.post(test.url + "/api/open", data={"archive": archives[0]["id"]})
    test.assertTrue(response.ok, response.text())
    test.assertTrue(response.json()["readonly"])
    test.page.goto(test.url + "/lab/" + response.json()["experiment"] + "/#instrument")
    expect(test.page.locator("#workspace")).to_be_visible()


def enable_output(test):
    """Turn on the selected instrument's declared detector from its apparatus part."""
    page = test.page
    state = page.request.get(test.url + "/api/state").json()
    device = next(d for d in state["definition"]["devices"] if d["id"] == state["device"])
    output = device.get("input")
    if not output or state["output_enabled"].get(output):
        return
    page.locator("[data-page='setup']").click()
    page.locator("#operation-tab").click()
    with page.expect_response(lambda r: r.url.endswith('/api/action') and
                              r.request.post_data_json.get('action') == 'output') as enabled:
        page.locator(f"#output-{output}").check()
    test.assertTrue(enabled.value.ok, enabled.value.text())
    expect(page.locator(f"#output-{output}")).to_be_checked()
    page.locator("[data-page='instrument']").click()


def measurement_operation(page, action):
    if action == 'save':
        page.locator('#save-current').click()
        page.locator('#measurement-save-confirm').click()
    elif action == 'clear':
        page.locator('#clear').click()
    else:
        page.get_by_role('button', name={'cache': '从本场实验记录选择', 'file': '从文件选择'}[action], exact=True).click()


def expect_counter_exposure(page, seconds, device='counter'):
    """Check cumulative exposure from the visible per-window ledger, including a partial row."""
    page.wait_for_function("""({device, seconds}) => {
        const panel = document.querySelector(`.counter-window[data-device="${device}"]`);
        if (!panel) return false;
        const cells = [...panel.querySelectorAll('tbody tr td:nth-child(2)')];
        return Math.abs(cells.reduce((sum, cell) => sum + Number(cell.textContent.replaceAll(',', '')), 0) - seconds) < 1e-8;
    }""", arg={'device': device, 'seconds': seconds})


def start_collection(test, seconds):
    """Use visible instrument controls, including a new round after reaching its limit."""
    page = test.page
    page.locator("[data-page='instrument']").click()
    state = page.request.get(test.url + "/api/state").json()
    instrument = state.get("instrument")
    grouped = page.locator('.counter-window').count() > 1
    targets = state.get('instruments', {}) if grouped else {state['device']: instrument}
    if any(target and target['stop_reason'] in ('time_limit', 'count_limit') for target in targets.values()):
        with page.expect_response(lambda r: r.url.endswith('/api/action') and
                                  r.request.post_data_json.get('action') == 'begin_clear_group') as clearing:
            measurement_operation(page, "clear")
        test.assertTrue(clearing.value.ok, clearing.value.text())
        if clearing.value.json().get("clear_confirmation"):
            expect(page.locator("#clear-discard")).to_be_visible()
            with page.expect_response(lambda r: r.url.endswith('/api/action') and
                                      r.request.post_data_json.get('action') == 'finish_clear_group') as cleared:
                page.locator("#clear-discard").click()
            test.assertTrue(cleared.value.ok, cleared.value.text())
            expect(page.locator("#clear-discard")).not_to_be_visible()
    expect(page.locator("#start")).to_be_enabled()
    enable_output(test)
    if state["definition"]["devices"][0]["kind"] == "spectrum":
        page.get_by_role("tab", name="采集", exact=True).click()
    page.locator("#mode").select_option("timed")
    page.locator("#duration").fill(str(seconds))
    page.locator("#apply-acquisition").click()
    page.locator("#start").click()
    expect(page.locator("#stop")).to_be_enabled()


@unittest.skipUnless(sync_playwright, "Install Playwright to run browser checks")
class CatalogRecordsBrowserTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        executable = Path(os.environ.get("NUCLEMU_TEST_BROWSER", self.playwright.chromium.executable_path))
        if not executable.is_file():
            self.skipTest("Install Chromium or set NUCLEMU_TEST_BROWSER")
        self.browser = self.playwright.chromium.launch(executable_path=executable)
        self.addCleanup(self.browser.close)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        Path(self.folder.name, "course.py").write_text(EXTERNAL, encoding="utf-8")
        self.now = 0
        self.server = make_server([self.folder.name], directory=self.folder.name, clock=lambda: self.now)
        self.worker = Thread(target=self.server.serve_forever)
        self.worker.start()
        self.addCleanup(self.stop_server)
        self.page = self.browser.new_page(viewport={"width": 1366, "height": 768}, accept_downloads=True)
        self.addCleanup(self.page.close)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.page.goto(self.url)
        expect(self.page.locator("[data-experiment='alpha']")).to_be_visible()

    def stop_server(self):
        self.server.shutdown()
        self.worker.join()
        self.server.server_close()

    def screenshot(self, name):
        output = os.environ.get("NUCLEMU_REVIEW_OUTPUT")
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=directory / (name + ".png"), full_page=True)

    def enter(self, experiment):
        entry = self.page.locator(f"[data-experiment='{experiment}']")
        entry.focus()
        entry.press("Enter")
        expect(self.page.locator("#workspace")).to_be_visible()
        expect(self.page.locator("#lab-title")).to_be_focused()

    def records(self):
        self.page.locator("[data-page=records]").click()
        expect(self.page.locator("#records-title")).to_have_text("实验记录")

    def collect(self, seconds):
        start_collection(self, seconds)
        self.now += seconds
        expect(self.page.locator("#stop")).to_be_disabled()

    def test_guide_and_empty_states_at_desktop_width(self):
        card = self.page.locator("article").filter(has=self.page.locator("[data-experiment='alpha']"))
        guide = card.get_by_role("button", name="查看资料")
        guide.focus()
        guide.press("Enter")
        expect(self.page.locator("#guide")).to_be_visible()
        self.assertIsNone(self.page.request.get(self.url + "/api/state").json())
        self.page.keyboard.press("Escape")
        expect(guide).to_be_focused()
        expect(self.page.locator("#archives, .archive-empty, .archive-table")).to_have_count(0)
        expect(self.page.locator("#catalog-load")).to_be_visible()
        self.page.set_viewport_size({"width": 1366, "height": 844})
        self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth"), 1366)
        expect(card.get_by_role("button", name="进入实验", exact=True)).to_be_visible()
        self.screenshot("catalog-empty-1366")
        self.enter("alpha")
        self.records()
        expect(self.page.locator(".product-empty")).to_be_visible()
        expect(self.page.locator(".product-empty")).to_have_text("当前没有实验记录，请进行测量或在本页面导入")
        expect(self.page.locator("#choose-import")).to_be_enabled()
        expect(self.page.locator("#export")).to_have_count(0)
        self.screenshot("records-empty-desktop")
        self.page.locator("#menu-file").click()
        self.page.locator("#leave").click()
        expect(self.page.locator("#confirm")).to_be_visible()
        self.page.locator("#discard").click()
        expect(self.page.locator("[data-experiment='alpha']")).to_be_focused()
        self.server.app.definitions.clear()
        self.page.reload()
        expect(self.page.locator(".catalog-empty")).to_have_text("没有可用实验。")

    def test_multi_device_selection_formats_download_and_archive(self):
        self.enter("records-test")
        self.collect(1.25)
        self.collect(.75)
        self.records()
        rows = self.page.locator("#products .product")
        expect(rows).to_have_count(4)
        expect(rows.nth(0)).to_have_attribute("data-device", "left")
        expect(rows.nth(1)).to_have_attribute("data-device", "right")
        expect(rows.nth(0)).to_contain_text("计数器（device-left）")
        expect(rows.nth(1)).to_contain_text("计数器（device-right）")
        expect(rows.nth(0).locator(".product-exposure")).to_have_text("1.25 s")
        all_rows = self.page.get_by_role("checkbox", name="全选", exact=True)
        all_rows.check()
        expect(self.page.locator(".product-selection output")).to_have_text("已选 4 / 4 项")
        rows.nth(1).locator("input").uncheck()
        self.assertTrue(all_rows.evaluate("node => node.indeterminate"))
        all_rows.check()
        all_rows.uncheck()
        expect(self.page.locator("#export")).to_be_disabled()
        all_rows.check()
        rows.nth(1).locator("select").select_option("json")
        rows.nth(2).locator("select").select_option("json")
        self.page.locator("[data-page='instrument']").click()
        self.records()
        expect(rows.nth(1).locator("select")).to_have_value("json")
        self.screenshot("records-desktop")
        with self.page.expect_download() as pending:
            self.page.locator("#export").click()
        download = pending.value
        destination = Path(self.folder.name) / "products.zip"
        download.save_as(destination)
        with ZipFile(destination) as bundle:
            names = bundle.namelist()
            self.assertEqual(len(names), 4)
            csv_name = next(name for name in names if "left-segment-1.csv" in name)
            first = list(csv.DictReader(io.StringIO(bundle.read(csv_name).decode("utf-8-sig"))))
            self.assertEqual(first[0]["counts"], "4")
            self.assertEqual(first[0]["exposure_s"], "1.25")
            json_name = next(name for name in names if "right-segment-1.json" in name)
            product = json.loads(bundle.read(json_name))
            self.assertEqual(product["segments"][0]["readings"], {"right": [14]})
        self.page.locator("#menu-file").click()
        self.page.locator("#leave").click()
        self.page.locator("#save-exit").click()
        expect(self.page.locator("[data-experiment='records-test']")).to_be_focused()
        expect(self.page.locator(".archive-table")).to_have_count(0)
        self.screenshot("catalog-archive-desktop")
        open_legacy_archive(self)
        expect(self.page.locator("#start")).to_be_disabled()
        # Explicit API restoration boots the page; the selector remains keyboard focusable.
        self.page.locator("#device").focus()
        expect(self.page.locator("#device")).to_be_focused()
        self.records()
        expect(self.page.locator("#products .product")).to_have_count(4)
        expect(self.page.locator(".product-selection output")).to_have_text("已选 0 / 4 项")
        expect(self.page.locator("#export")).to_be_disabled()
        expect(self.page.locator(".product-exposure").first).to_have_text("1.25 s")

    def test_calibration_product_single_json_download(self):
        self.enter("alpha")
        self.collect(.25)
        self.page.get_by_role("tab", name="谱分析", exact=True).click()
        self.page.locator("details.calibration-tools > summary").click()
        for field, value in (("c1", 0), ("e1", 0), ("c2", 1000), ("e2", 6)):
            self.page.locator(f"[name='{field}']").fill(str(value))
        self.page.locator("#calibrate button").click()
        expect(self.page.locator("#save-calibration")).to_be_enabled()
        self.page.locator("#save-calibration").click()
        self.page.locator('#calibration-save-confirm').click()
        expect(self.page.locator("#calibration-notice")).to_contain_text("刻度已保存")
        self.records()
        row = self.page.locator('.product').filter(has=self.page.get_by_text('能量刻度', exact=True))
        expect(row).to_be_visible()
        expect(row.locator(".product-exposure")).to_have_text("—")
        expect(row.locator("select option")).to_have_count(1)
        row.locator("input").check()
        self.screenshot("records-calibration")
        with self.page.expect_download() as pending:
            self.page.locator("#export").click()
        download = pending.value
        self.assertTrue(download.suggested_filename.endswith(".json"))
        destination = Path(self.folder.name) / "calibration.json"
        download.save_as(destination)
        bundle = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(bundle["format"], "nuclemu.item/1")
        self.assertEqual(len(bundle["items"]), 1)
        self.assertEqual(bundle["items"][0]["kind"], "calibration")
        calibration = bundle["items"][0]["document"]
        self.assertEqual(calibration["format"], "nuclemu.calibration/1")
        self.assertEqual(calibration["device"], "mca")
        self.assertEqual(calibration["energy2"], 6)


if __name__ == "__main__":
    unittest.main()
