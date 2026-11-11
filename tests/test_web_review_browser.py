"""PR review regressions for joining pages and preserving visible operation targets."""

import json
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.catalog import discover
from nuclemu.web_session import Application

if fixtures.sync_playwright:
    from playwright.sync_api import expect


SPECTRA = """
from nuclemu.core import Device, Experiment, Parameter
def measure(settings, start, end, rng):
    return {'left': [0, 4, 0, 0], 'right': [0, 0, 6, 0]}
EXPERIMENT = Experiment('spectra-review', '两台谱仪', '核对刻度目标',
    (Parameter('gain', '增益', '', 1, 1, 4, True),),
    (Device('left', 'spectrum', '左谱仪', 4, ('gain',)),
     Device('right', 'spectrum', '右谱仪', 4, ('gain',))), measure)
"""


@unittest.skipUnless(fixtures.sync_playwright, "Install Playwright to run browser checks")
class WebReviewBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot
    enter = fixtures.CatalogRecordsBrowserTests.enter
    collect = fixtures.CatalogRecordsBrowserTests.collect

    def peer(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(self.url)
        expect(page.locator("#catalog")).to_be_visible()
        return page

    def state(self):
        return self.page.request.get(self.url + "/api/state").json()

    def exit_dialog(self, page):
        page.locator("#menu-file").click()
        page.locator("#leave").click()
        expect(page.locator("#confirm")).to_be_visible()

    def start(self, seconds):
        self.page.locator("[data-page='instrument']").click()
        self.page.locator("#menu-acquisition").click()
        self.page.locator("#duration").fill(str(seconds))
        self.page.keyboard.press("Escape")
        self.page.locator("#start").click()
        expect(self.page.locator("#gate-status")).to_have_text("采集中")

    @staticmethod
    def hold_poll(page, snapshot):
        # Freeze only this page's displayed snapshot, leaving actual operations and
        # the explicit stale-confirmation refresh free to reach the real server.
        active = [True]
        def route(request):
            if "product_cursor=" in request.request.url and active[0]:
                request.fulfill(json=snapshot)
            else:
                active[0] = False
                request.continue_()
        page.route("**/api/state?*", route)
        return lambda: (active.__setitem__(0, False), page.unroute("**/api/state?*", route))

    def test_two_catalogues_join_same_live_session_but_not_other_experiments(self):
        peer, other = self.peer(), self.peer()
        self.enter("alpha")
        self.collect(1.25)
        self.start(10)
        self.now += .5
        before = self.state()
        peer.locator("[data-experiment='alpha']").click()
        expect(peer.locator("#workspace")).to_be_visible()
        expect(peer.locator("#lab-title")).to_be_focused()
        joined = self.state()
        self.assertEqual(joined["id"], before["id"])
        self.assertEqual(joined["product"], before["product"])
        self.assertTrue(joined["running"])
        self.assertEqual(joined["remaining_s"], 9.5)
        expect(peer.locator("#recovered")).to_have_count(0)
        other.locator("[data-experiment='beta']").click()
        expect(other.locator("#error")).to_be_visible()
        expect(other.locator("#catalog")).to_be_visible()
        self.assertEqual(self.state()["id"], before["id"])

    def test_refresh_keeps_live_gate_without_draft_notice_and_explicit_draft_shows_time(self):
        self.enter("alpha")
        self.start(10)
        self.now = 1.5
        expect(self.page.locator("#time")).to_have_text("1.5 s")
        before = self.state()
        self.page.reload()
        expect(self.page.locator("#gate-status")).to_have_text("采集中")
        expect(self.page.locator("#recovered")).to_have_count(0)
        after = self.state()
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["product"], before["product"])
        self.assertEqual(after["remaining_s"], 8.5)
        self.screenshot("review-live-refresh")
        # Restart only the application with its existing isolated on-disk store.
        self.page.goto("about:blank")
        with self.server.app_lock:
            self.server.app = Application(self.server.app.definitions, self.folder.name, lambda: self.now)
        self.page.goto(self.url)
        self.page.get_by_role("button", name="打开草稿", exact=True).click()
        expect(self.page.locator("#recovered")).to_contain_text("1 s")
        expect(self.page.locator("#device")).to_be_focused()
        self.assertTrue(self.state()["readonly"])
        self.screenshot("review-explicit-draft")
        self.page.reload()
        expect(self.page.locator("#recovered")).to_have_text("正在查看已保存的实验。")

    def test_stale_save_and_discard_cannot_touch_resumed_gate_or_new_draft(self):
        peer = self.peer()
        self.enter("alpha")
        peer.locator("[data-experiment='alpha']").click()
        expect(peer.locator("#workspace")).to_be_visible()
        self.start(10)
        self.now = .25
        for button in ("save-exit", "discard"):
            self.exit_dialog(self.page)
            expect(peer.locator("#confirm")).to_be_visible()
            old = self.state()
            release = self.hold_poll(peer, old)
            self.page.locator("#cancel").click()
            expect(self.page.locator("#confirm")).not_to_be_visible()
            self.now += 1
            before = self.state()
            draft = self.server.app.store.read(self.server.app.lab.draft_id)
            peer.locator("#" + button).click()
            expect(peer.locator("#error")).to_contain_text("过期")
            after = self.state()
            self.assertTrue(after["running"])
            self.assertEqual(after["id"], before["id"])
            self.assertEqual(after["product"], before["product"])
            self.assertEqual(self.server.app.store.read(self.server.app.lab.draft_id), draft)
            self.assertEqual(self.server.app.catalog()["archives"], [])
            release()
            self.screenshot("review-stale-" + button)
            # Let the page observe the resumed state before starting another round.
            expect(peer.locator("#confirm")).not_to_be_visible()

    def test_save_failure_keeps_confirmation_for_retry(self):
        self.enter("alpha")
        self.collect(1.25)
        self.start(10)
        self.now += .25
        self.exit_dialog(self.page)
        before = self.state()
        write = self.server.app.store.write
        def fail(*args, **kwargs):
            raise OSError("browser review save failure")
        self.server.app.store.write = fail
        try:
            self.page.locator("#save-exit").click()
            expect(self.page.locator("#exit-error")).to_contain_text("save failure")
            after = self.state()
            self.assertEqual(after["confirmation_id"], before["confirmation_id"])
            self.assertTrue(after["frozen"])
            self.assertTrue(after["running"])
            self.assertEqual(after["remaining_s"], before["remaining_s"])
        finally:
            self.server.app.store.write = write
        self.page.locator("#save-exit").click()
        expect(self.page.locator("[data-experiment='alpha']")).to_be_focused()
        self.assertIsNone(self.state())

    def test_visible_old_confirmation_does_not_adopt_a_new_round_from_polling(self):
        peer = self.peer()
        self.enter("alpha")
        peer.locator("[data-experiment='alpha']").click()
        expect(peer.locator("#workspace")).to_be_visible()
        self.start(10)
        self.exit_dialog(self.page)
        expect(peer.locator("#confirm")).to_be_visible()
        first = self.state()
        release = self.hold_poll(peer, first)
        self.page.locator("#cancel").click()
        expect(self.page.locator("#confirm")).not_to_be_visible()
        self.exit_dialog(self.page)
        second = self.state()
        self.assertNotEqual(first["confirmation_id"], second["confirmation_id"])
        release()
        peer.wait_for_timeout(700)
        with peer.expect_request(lambda r: r.url.endswith("/api/action") and
                                 r.post_data_json.get("action") == "continue") as pending:
            peer.locator("#cancel").click()
        self.assertEqual(pending.value.post_data_json["confirmation_id"], first["confirmation_id"])
        expect(peer.locator("#error")).to_contain_text("过期")
        current = self.state()
        self.assertEqual(current["confirmation_id"], second["confirmation_id"])
        self.assertTrue(current["frozen"])
        # The page can explicitly open the current confirmation and continue safely.
        self.exit_dialog(peer)
        peer.locator("#cancel").click()
        expect(peer.locator("#confirm")).not_to_be_visible()
        self.assertFalse(self.state()["frozen"])

    def test_archive_request_cannot_join_live_experiment_of_same_name(self):
        self.enter("alpha")
        self.collect(1)
        self.exit_dialog(self.page)
        self.page.locator("#save-exit").click()
        expect(self.page.locator("#catalog")).to_be_visible()
        peer = self.peer()
        self.enter("alpha")
        live = self.state()
        peer.get_by_role("button", name="查看实验", exact=True).click()
        expect(peer.locator("#error")).to_be_visible()
        self.assertEqual(self.state()["id"], live["id"])
        self.assertFalse(self.state()["readonly"])
        self.exit_dialog(self.page)
        self.page.locator("#discard").click()
        expect(self.page.locator("#catalog")).to_be_visible()
        # A fresh experiment request must not attach to an already-open archive.
        fresh = self.peer()
        self.page.get_by_role("button", name="查看实验", exact=True).click()
        expect(self.page.locator("#start")).to_be_disabled()
        archived = self.state()
        fresh.locator("[data-experiment='alpha']").click()
        expect(fresh.locator("#error")).to_be_visible()
        self.assertEqual(self.state()["id"], archived["id"])
        self.assertTrue(self.state()["readonly"])
        # Explicitly opening this same archive is an idempotent read-only attach.
        peer.get_by_role("button", name="查看实验", exact=True).click()
        expect(peer.locator("#device")).to_be_focused()
        self.assertEqual(self.state()["id"], archived["id"])

    def spectra(self):
        Path(self.folder.name, "spectra.py").write_text(SPECTRA, encoding="utf-8")
        self.server.app.definitions = discover([self.folder.name])
        self.page.reload()
        peer = self.peer()
        self.enter("spectra-review")
        self.collect(1)
        peer.locator("[data-experiment='spectra-review']").click()
        expect(peer.locator("#workspace")).to_be_visible()
        peer.locator("[data-page='instrument']").click()
        return peer

    def save_and_reopen_analysis(self):
        self.exit_dialog(self.page)
        expected = json.loads(json.dumps(self.server.app.lab.analysis))
        self.page.locator("#save-exit").click()
        expect(self.page.locator("#catalog")).to_be_visible()
        self.page.get_by_role("button", name="查看实验", exact=True).click()
        expect(self.page.locator("#device")).to_be_focused()
        self.assertTrue(self.state()["readonly"])
        self.assertEqual(self.server.app.lab.analysis, expected)

    def test_explicit_apparatus_device_click_reasserts_displayed_instrument(self):
        peer = self.spectra()
        product = self.state()['product']
        for selector in ("[data-part='device-left']", '#component > button'):
            with self.subTest(selector=selector):
                self.page.locator("[data-page='setup']").click()
                release = self.hold_poll(self.page, self.state())
                peer.locator('#device').select_option('right')
                expect(peer.locator('#device')).to_have_value('right')
                with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                               r.request.post_data_json.get('action') == 'device') as selected:
                    self.page.locator(selector).click()
                self.assertTrue(selected.value.ok)
                self.assertEqual(selected.value.request.post_data_json['device'], 'left')
                expect(self.page.locator('#device')).to_be_focused()
                expect(self.page.locator('#device')).to_have_value('left')
                release()
                expect(peer.locator('#device')).to_have_value('left')
                current = self.state()
                self.assertEqual(current['device'], 'left')
                self.assertEqual(current['readout']['centroid'], 1)
                self.assertEqual(current['product'], product)
        self.page.locator("[data-page='setup']").click()
        self.page.route('**/api/action', lambda route: route.fulfill(
            status=400, json={'error': 'device selection failed'}))
        self.page.locator('#component > button').click()
        expect(self.page.locator('#error')).to_contain_text('device selection failed')
        expect(self.page.locator("[data-page='setup']")).to_have_attribute('aria-current', 'page')
        expect(self.page.locator('#setup')).to_be_visible()
        self.assertEqual(self.state()['product'], product)

    def test_counter_background_keeps_displayed_device_and_survives_archive(self):
        peer = self.peer()
        self.enter("records-test")
        self.collect(1)
        self.collect(2)
        peer.locator("[data-experiment='records-test']").click()
        peer.locator("[data-page='instrument']").click()
        release = self.hold_poll(self.page, self.state())
        peer.locator("#device").select_option("right")
        expect(peer.locator("#device")).to_have_value("right")
        before = json.loads(json.dumps(self.server.app.lab.analysis))
        with self.page.expect_request(lambda r: r.url.endswith('/api/action') and
                                      r.post_data_json.get('action') == 'analysis') as pending:
            self.page.locator("#background").select_option("0")
        self.assertEqual(pending.value.post_data_json['device'], 'left')
        expect(self.page.locator("#error")).to_contain_text("设备已改变")
        self.assertEqual(self.server.app.lab.analysis, before)
        release()
        expect(self.page.locator("#device")).to_have_value("right")
        self.page.locator("#background").select_option("1")
        expect(self.page.locator("#background")).to_have_value("1")
        self.page.locator("#device").select_option("left")
        expect(self.page.locator("#background")).to_have_value("")
        self.page.locator("#background").select_option("0")
        expect(self.page.locator("#background")).to_have_value("0")
        self.save_and_reopen_analysis()
        expect(self.page.locator("#background")).to_have_value("0")
        self.page.locator("#device").select_option("right")
        expect(self.page.locator("#background")).to_have_value("1")

    def test_spectrum_history_reference_and_display_keep_device_and_survive_archive(self):
        peer = self.spectra()
        self.collect(2)
        self.page.locator("#menu-display").click()
        release = self.hold_poll(self.page, self.state())
        peer.locator("#device").select_option("right")
        expect(peer.locator("#device")).to_have_value("right")
        before = json.loads(json.dumps(self.server.app.lab.analysis))
        for selector, value in (("#sample", "0"), ("#reference", "0"), ("#rate", None)):
            with self.subTest(selector=selector):
                with self.page.expect_response(lambda r: r.url.endswith('/api/action')) as pending:
                    if value is None:
                        self.page.locator(selector).check()
                    else:
                        self.page.locator(selector).select_option(value)
                self.assertEqual(pending.value.status, 400)
                self.assertEqual(pending.value.request.post_data_json['device'], 'left')
                expect(self.page.locator("#error")).to_contain_text("设备已改变")
                self.assertEqual(self.server.app.lab.analysis, before)
        release()
        expect(self.page.locator("#device")).to_have_value("right")
        self.page.locator("#sample").select_option("1")
        self.page.locator("#reference").select_option("0")
        self.page.locator("#rate").check()
        expect(self.page.locator("#sample")).to_have_value("1")
        self.page.keyboard.press("Escape")
        self.page.locator("#device").select_option("left")
        expect(self.page.locator("#device")).to_have_value("left")
        self.page.locator("#menu-display").click()
        self.page.locator("#sample").select_option("0")
        self.page.locator("#reference").select_option("1")
        expect(self.page.locator("#sample")).to_have_value("0")
        self.page.keyboard.press("Escape")
        self.save_and_reopen_analysis()
        self.page.locator("#menu-display").click()
        expect(self.page.locator("#sample")).to_have_value("0")
        expect(self.page.locator("#reference")).to_have_value("1")
        expect(self.page.locator("#rate")).not_to_be_checked()
        self.page.keyboard.press("Escape")
        self.page.locator("#device").select_option("right")
        self.page.locator("#menu-display").click()
        expect(self.page.locator("#sample")).to_have_value("1")
        expect(self.page.locator("#reference")).to_have_value("0")
        expect(self.page.locator("#rate")).to_be_checked()

    def fill_calibration(self):
        if self.page.locator("#menu-analysis").get_attribute("aria-expanded") != "true":
            self.page.locator("#menu-analysis").click()
        if self.page.locator("details.calibration-tools").get_attribute("open") is None:
            self.page.locator("details.calibration-tools > summary").click()
        for name, value in (("c1", 0), ("e1", 0), ("c2", 2), ("e2", 1)):
            self.page.locator(f"[name='{name}']").fill(str(value))

    def test_stale_manual_and_drag_roi_cannot_change_another_instrument(self):
        peer = self.spectra()
        self.page.locator("#menu-analysis").click()
        self.page.locator("#first").fill("1")
        self.page.locator("#last").fill("2")
        release = self.hold_poll(self.page, self.state())
        peer.locator("#device").select_option("right")
        expect(peer.locator("#device")).to_have_value("right")
        before = json.loads(json.dumps(self.server.app.lab.analysis))
        self.page.locator("#roi button").click()
        expect(self.page.locator("#error")).to_contain_text("所用设备已改变")
        self.assertEqual(self.server.app.lab.analysis, before)
        box = self.page.locator("#plot").bounding_box()
        self.page.mouse.move(box["x"] + box["width"] * .25, box["y"] + box["height"] * .5)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] * .6, box["y"] + box["height"] * .5)
        self.page.mouse.up()
        expect(self.page.locator("#error")).to_contain_text("所用设备已改变")
        self.assertEqual(self.server.app.lab.analysis, before)
        release()
        expect(self.page.locator("#device")).to_have_value("right")
        self.page.locator("#first").fill("1")
        self.page.locator("#last").fill("2")
        self.page.locator("#roi button").click()
        self.page.wait_for_function("document.querySelector('#peak').textContent.includes('选区峰心')")
        self.assertEqual(self.server.app.lab.analysis["right"]["roi"], [1, 2])
        self.assertEqual(self.server.app.lab.analysis["left"]["roi"], [0, 3])

    def pending_calibration_file(self):
        self.fill_calibration()
        self.page.evaluate("""() => {
            const text = window.originalFileText ??= File.prototype.text;
            File.prototype.text = function() {
                return new Promise(resolve => { window.finishFile = () => text.call(this).then(resolve) })
            }
        }""")
        document = dict(format="nuclemu.calibration/2", unit="MeV", experiment="spectra-review",
                        device="left", channels=4, channel1=0, energy1=0, channel2=2, energy2=1,
                        conditions={"gain": 1})
        with self.page.expect_file_chooser() as pending:
            self.page.locator("#cal-file").click()
        pending.value.set_files({"name": "energy.json", "mimeType": "application/json",
                                 "buffer": json.dumps(document).encode()})
        self.page.wait_for_function("typeof window.finishFile === 'function'")

    def test_file_read_cannot_write_into_reentered_identical_session(self):
        self.spectra()
        self.pending_calibration_file()
        original = self.state()
        self.exit_dialog(self.page)
        self.page.locator("#discard").click()
        expect(self.page.locator("#catalog")).to_be_visible()
        self.enter("spectra-review")
        self.collect(1)
        current = self.state()
        self.assertNotEqual(current["id"], original["id"])
        self.assertEqual(current["calibration_context"], original["calibration_context"])
        self.page.evaluate("window.finishFile()")
        expect(self.page.locator("#error")).to_contain_text("实验已变更")
        self.assertEqual(self.server.app.lab.work.lab.calibrations, {})
        self.assertEqual(self.state()["product"], current["product"])

    def test_delayed_file_import_succeeds_in_same_session_and_rejects_changed_gain(self):
        peer = self.spectra()
        self.pending_calibration_file()
        with self.page.expect_response(lambda r: r.url.endswith('/api/action') and
                                       r.request.post_data_json.get('action') == 'load_calibration') as imported:
            self.page.evaluate("window.finishFile()")
        self.assertTrue(imported.value.ok, imported.value.text())
        self.assertEqual(dict(self.server.app.lab.work.lab.calibrations["left"].conditions), {"gain": 1})
        self.pending_calibration_file()
        peer.locator("[data-page='setup']").click()
        peer.locator("#component input").fill("2")
        peer.locator("#component form button").click()
        expect(peer.locator("#message")).to_contain_text("已更新")
        self.collect(1)
        before = self.server.app.lab.work.lab.calibrations.copy()
        self.page.evaluate("window.finishFile()")
        expect(self.page.locator("#error")).to_contain_text("适用工况已改变")
        self.assertEqual(self.server.app.lab.work.lab.calibrations, before)

    def test_stale_form_and_file_read_keep_original_device_context(self):
        peer = self.spectra()
        self.fill_calibration()
        release = self.hold_poll(self.page, self.state())
        peer.locator("#device").select_option("right")
        expect(peer.locator("#device")).to_have_value("right")
        self.page.locator("#calibrate button").click()
        expect(self.page.locator("#error")).to_contain_text("改变")
        self.assertEqual(self.server.app.lab.work.lab.calibrations, {})
        release()
        peer.locator("#device").select_option("left")
        expect(self.page.locator("#device")).to_have_value("left")
        # Keep File.text pending while the other page changes the instrument.
        self.page.evaluate("""() => {
            const text = File.prototype.text;
            File.prototype.text = function() {
                return new Promise(resolve => { window.finishFile = () => text.call(this).then(resolve) })
            }
        }""")
        document = dict(format="nuclemu.calibration/2", unit="MeV", experiment="spectra-review",
                        device="left", channels=4, channel1=0, energy1=0, channel2=2, energy2=1,
                        conditions={"gain": 1})
        if self.page.locator("#menu-analysis").get_attribute("aria-expanded") != "true":
            self.page.locator("#menu-analysis").click()
        if self.page.locator("details.calibration-tools").get_attribute("open") is None:
            self.page.locator("details.calibration-tools > summary").click()
        with self.page.expect_file_chooser() as pending:
            self.page.locator("#cal-file").click()
        pending.value.set_files({"name": "energy.json", "mimeType": "application/json",
                                 "buffer": json.dumps(document).encode()})
        self.page.wait_for_function("typeof window.finishFile === 'function'")
        peer.locator("#device").select_option("right")
        expect(peer.locator("#device")).to_have_value("right")
        self.page.evaluate("window.finishFile()")
        expect(self.page.locator("#error")).to_contain_text("改变")
        self.assertEqual(self.server.app.lab.work.lab.calibrations, {})
        self.screenshot("review-calibration-context")

    def test_history_change_rejects_old_form_and_explicit_history_uses_its_gain(self):
        peer = self.spectra()
        peer.locator("[data-page='setup']").click()
        peer.locator("#component input").fill("2")
        peer.locator("#component form button").click()
        expect(peer.locator("#message")).to_contain_text("已更新")
        self.collect(1)
        self.page.locator("#menu-display").click()
        self.page.locator("#sample").select_option("0")
        expect(self.page.locator("#sample")).to_have_value("0")
        self.page.keyboard.press("Escape")
        self.fill_calibration()
        release = self.hold_poll(self.page, self.state())
        peer.locator("[data-page='instrument']").click()
        peer.locator("#menu-display").click()
        peer.locator("#sample").select_option("1")
        expect(peer.locator("#sample")).to_have_value("1")
        self.page.locator("#calibrate button").click()
        expect(self.page.locator("#error")).to_contain_text("改变")
        self.assertEqual(self.server.app.lab.work.lab.calibrations, {})
        release()
        expect(self.page.locator("#device")).to_have_value("left")
        # Choose gain=1 history deliberately while the live apparatus remains gain=2.
        if self.page.locator("#menu-display").get_attribute("aria-expanded") != "true":
            self.page.locator("#menu-display").click()
        self.page.locator("#sample").select_option("0")
        expect(self.page.locator("#sample")).to_have_value("0")
        self.page.keyboard.press("Escape")
        self.fill_calibration()
        self.page.locator("#calibrate button").click()
        self.page.wait_for_function("document.querySelector('#calibrate [name=c2]').value === '2'")
        expect(self.page.locator("#error")).not_to_be_visible()
        self.page.locator("#menu-display").click()
        expect(self.page.locator("#energy")).to_be_enabled()
        calibration = self.server.app.lab.work.lab.calibrations["left"]
        self.assertEqual(dict(calibration.conditions), {"gain": 1})
        self.assertEqual(self.state()["settings"]["gain"], 2)
