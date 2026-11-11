"""Real local archives and deterministic clocks exercise Web session behavior."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.core import Device, Experiment, Parameter, Session
from nuclemu.results import collect
from nuclemu.web_session import Application


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class WebSessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock()
        self.definitions = discover()
        self.app = Application(self.definitions, self.folder.name, self.clock)

    def open(self, name="beta", **kwargs):
        return self.app.open(dict(experiment=name, seed=187, **kwargs))

    def action(self, action, **kwargs):
        if action in ("continue", "discard") or (action == "save" and kwargs.get("exit") is True):
            if not self.app.lab.frozen:
                self.action("freeze")
            kwargs.setdefault("confirmation_id", self.app.lab.confirmation_id)
        if action in ("calibrate", "load_calibration"):
            kwargs.setdefault("calibration_context", self.app.lab.calibration_context())
        return self.app.request("/api/action", dict(session=self.app.lab.id, action=action, **kwargs))

    def acquire(self, duration, **settings):
        if settings:
            self.action("configure", values=settings)
        self.action("start", duration=duration)
        self.clock.now += duration
        return self.app.state(session=self.app.lab.id)

    def test_failed_save_at_14_5_of_60_can_resume_original_rng_and_endpoint(self):
        self.open("alpha")
        self.action("start", duration=60)
        self.clock.now = 14.5
        self.action("freeze")
        before = deepcopy(self.app.lab.state())
        rng_state = self.app.lab.work.session._rng.getstate()

        def fail(*args, **kwargs):
            self.clock.now += 100
            raise sqlite3.OperationalError("disk full")

        with patch.object(self.app.store, "write", side_effect=fail):
            with self.assertRaisesRegex(sqlite3.Error, "disk full"):
                self.action("save", exit=True)
        after = self.app.lab.state()
        self.assertEqual(after["product"], before["product"])
        self.assertEqual(self.app.lab.work.session._rng.getstate(), rng_state)
        self.assertTrue(after["running"])
        self.assertTrue(after["frozen"])
        self.assertEqual(after["time_s"], 14.5)
        self.assertEqual(after["remaining_s"], 45.5)
        self.assertTrue(after["dirty"])
        self.action("continue")
        self.clock.now += 45.5
        final = self.app.state()
        reference = Session(self.definitions["alpha"], seed=187)
        reference.start(60)
        reference.advance(60)
        self.assertEqual(final["product"], collect(reference.experiment, reference.records, 187))
        self.assertFalse(final["running"])
        self.assertEqual(final["time_s"], 60)

    def test_successful_save_exit_includes_partial_exposure_and_removes_draft(self):
        self.open("alpha")
        self.action("start", duration=60)
        self.clock.now = 14.5
        self.action("freeze")
        expected = deepcopy(self.app.lab.document(finish=True))
        self.assertIsNone(self.action("save", exit=True))
        self.assertIsNone(self.app.lab)
        catalog = self.app.catalog()
        self.assertEqual(catalog["drafts"], [])
        self.assertEqual(len(catalog["archives"]), 1)
        app = Application(self.definitions, self.folder.name, self.clock)
        restored = app.open({"archive": catalog["archives"][0]["id"]})
        self.assertEqual(restored["product"], expected["product"])
        self.assertEqual(restored["time_s"], 14.5)
        self.assertTrue(restored["readonly"])
        self.assertFalse(restored["dirty"])

    def test_normal_save_uses_only_closed_windows_and_counts_do_not_regress(self):
        self.open("alpha")
        self.action("start", duration=2)
        self.clock.now = 0.75
        self.app.state()
        rng = self.app.lab.work.session._rng.getstate()
        with patch.object(self.app.lab.work.session, "preview_stop", side_effect=AssertionError("Extra sampling")):
            state = self.action("save")
        self.assertEqual(state["remaining_s"], 1.25)
        self.assertTrue(state["running"])
        self.assertEqual(self.app.lab.work.session._rng.getstate(), rng)
        self.assertEqual(self.app.catalog()["drafts"], [])
        doc = self.app.store.read(self.app.lab.archive_id)
        self.assertEqual(doc["product"]["segments"], [])
        self.assertEqual(doc["measurement_end_s"], 0)
        self.clock.now = 1.75
        closed = deepcopy(self.app.state()["product"])
        with patch.object(self.app.lab.work.session, "preview_stop", side_effect=AssertionError("Extra sampling")):
            self.action("save")
        doc = self.app.store.read(self.app.lab.archive_id)
        self.assertEqual(doc["product"], closed)
        self.assertEqual(doc["measurement_end_s"], 1)
        self.clock.now = 2
        finished = self.app.state()
        saved_counts = closed["segments"][0]["readings"]["mca"]
        final_counts = finished["product"]["segments"][0]["readings"]["mca"]
        self.assertTrue(all(after >= before for before, after in zip(saved_counts, final_counts)))
        reference = Session(self.definitions["alpha"], seed=187)
        reference.start(2)
        reference.advance(2)
        self.assertEqual(finished["product"], collect(reference.experiment, reference.records, 187))
        draft = self.app.store.read(self.app.lab.draft_id)
        self.assertEqual(draft["product"]["segments"][-1]["end_s"], 2)
        self.assertEqual(self.app.lab.state()["unsaved"]["measurements"][0]["end_s"], 2)

    def test_restart_preserves_two_backgrounds_selected_reference_and_net_rate(self):
        self.open()
        self.acquire(2.5, source_present=0)
        self.acquire(4.25)
        self.acquire(3.5, source_present=1, foil_count=4)
        self.action("analysis", background=1, reference=0)
        before = deepcopy(self.action("select", index=2))
        self.action("save", exit=True)
        app = Application(self.definitions, self.folder.name, self.clock)
        identifier = app.catalog()["archives"][0]["id"]
        restored = app.open({"archive": identifier})
        self.assertEqual(restored["analysis"], before["analysis"])
        self.assertEqual(restored["readout"], before["readout"])
        self.assertEqual(restored["product"], before["product"])
        self.assertEqual(restored["selected"], 2)

    def test_multi_instrument_roi_and_gain_bound_calibration_roundtrip(self):
        definition = Experiment("two", "Two spectra", "", (Parameter("gain", "Gain", "", 1, 1, 2),),
            (Device("left", "spectrum", "Left", 8, ("gain",)),
             Device("right", "spectrum", "Right", 8, ("gain",))),
            lambda settings, start, end, rng: {"left": (0, 3, 0, 0, 0, 0, 0, 0),
                                              "right": (0, 0, 0, 5, 0, 0, 0, 0)})
        self.definitions = {"two": definition}
        self.app = Application(self.definitions, self.folder.name, self.clock)
        self.open("two")
        self.acquire(1)
        self.action("calibrate", points=[0, 0, 7, 7])
        self.action("analysis", device="left", roi=[0, 2], reference=0)
        self.acquire(1, gain=2)
        self.assertIsNone(self.app.lab.state()["calibration"])
        old = self.action("select", device="left", index=0)
        self.assertEqual(old["settings"]["gain"], 2)
        self.assertEqual(old["spectrum_settings"]["gain"], 1)
        self.assertEqual(old["readout"]["energy_MeV"], 1)
        self.action("device", device="right")
        self.action("analysis", device="right", roi=[2, 4], reference=1)
        self.action("select", device="right", index=1)
        self.action("calibrate", points=[0, 0, 7, 14])
        before = deepcopy(self.app.lab.state())
        self.action("save", exit=True)
        app = Application(self.definitions, self.folder.name, self.clock)
        restored = app.open({"archive": app.catalog()["archives"][0]["id"]})
        self.assertEqual(restored["readout"], before["readout"])
        self.assertEqual(restored["analysis"]["roi"], [2, 4])
        self.assertEqual(restored["analysis"]["reference"], 1)
        self.assertEqual(restored["device"], "right")
        switched = app.request("/api/action", dict(session=app.lab.id, action="device", device="left"))
        self.assertEqual(switched["analysis"]["roi"], [0, 2])
        self.assertEqual(switched["selected"], 0)
        self.assertEqual(switched["readout"]["energy_MeV"], 1)

    def test_refresh_does_not_close_gate_and_restart_draft_reports_completed_endpoint(self):
        self.open()
        self.action("start", duration=60)
        self.clock.now = 14.5
        state = self.app.state()
        self.assertTrue(state["running"])
        self.assertEqual(state["recovered_s"], 14)
        repeat = self.app.state(session=state["id"])
        self.assertEqual(repeat["remaining_s"], 45.5)
        app = Application(self.definitions, self.folder.name, self.clock)
        recovered = app.open({"draft": True})
        self.assertEqual(recovered["time_s"], 14)
        self.assertEqual(recovered["recovered_s"], 14)
        self.assertFalse(recovered["running"])
        self.assertTrue(recovered["readonly"])
        self.assertTrue(recovered["dirty"])
        self.assertEqual(recovered["unsaved"]["measurements"][0]["index"], 0)

    def test_failed_draft_write_reports_old_recovery_time_then_retries(self):
        self.open()
        self.acquire(1)
        self.action("start", duration=2)
        self.clock.now += 1
        with patch.object(self.app.store, "write", side_effect=sqlite3.OperationalError("locked")):
            state = self.app.state()
        self.assertEqual(state["recovered_s"], 1)
        self.assertEqual(state["draft_error"], "locked")
        state = self.app.state()
        self.assertEqual(state["recovered_s"], 2)
        self.assertIsNone(state["draft_error"])

    def test_export_subset_keeps_unconfirmed_download_and_other_products_unsaved(self):
        self.open("alpha")
        self.acquire(1)
        self.acquire(1)
        self.action("calibrate", points=[0, 0, 1000, 6])
        before = deepcopy(self.app.lab.state()["unsaved"])
        exported = self.app.request("/api/export", dict(session=self.app.lab.id,
            format="json", device="mca", kind="measurement", indices=[0]))
        self.assertEqual(len(json.loads(exported)["segments"]), 1)
        state = self.app.lab.state()
        self.assertEqual(state["unsaved"], before)
        self.assertEqual(len(state["unsaved"]["measurements"]), 2)
        self.assertEqual(state["unsaved"]["calibrations"], ["mca"])
        self.assertIn("未确认", state["export_notice"])
        self.action("save")
        self.assertFalse(self.app.lab.state()["dirty"])
        self.action("analysis", roi=[800, 900])
        state = self.app.lab.state()
        self.assertEqual(state["unsaved"]["measurements"], [])
        self.assertEqual(state["unsaved"]["calibrations"], [])
        self.assertTrue(state["unsaved"]["analysis"])

    def test_old_or_missing_session_cannot_operate_or_tick_a_new_lab(self):
        old = self.open()["id"]
        self.action("discard")
        current = self.open("alpha")
        self.clock.now += 5
        for supplied in ({}, {"session": old}):
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                self.app.request("/api/action", dict(action="start", duration=10, **supplied))
        with self.assertRaises(ValueError):
            self.app.state(session=old)
        self.assertEqual(self.app.lab.time_s(), current["time_s"])
        self.assertFalse(self.app.lab.work.session.running)

    def test_exports_checkpoint_the_windows_closed_by_the_delivery_request(self):
        for route in ("/api/export", "/api/download"):
            with self.subTest(route=route):
                folder = Path(self.folder.name) / route.rsplit("/", 1)[-1]
                self.clock.now = 0
                self.app = Application(self.definitions, folder, self.clock)
                self.open()
                self.acquire(1)
                self.action("start", duration=2)
                self.clock.now = 2
                product = dict(format="json", kind="measurement", device="counter", indices=[1])
                body = product if route == "/api/export" else {"products": [product]}
                self.app.request(route, dict(session=self.app.lab.id, **body))
                app = Application(self.definitions, folder, self.clock)
                recovered = app.open({"draft": True})
                self.assertEqual(recovered["recovered_s"], 2)
                self.assertEqual(recovered["product"], self.app.lab.work.product())

    def test_pagehide_checkpoint_does_not_freeze_or_cancel_an_explicit_confirmation(self):
        self.open()
        self.action("start", duration=60)
        self.clock.now = 14.5
        leaving_page = self.action("suspend")
        self.assertFalse(leaving_page["frozen"])
        self.assertTrue(leaving_page["running"])
        self.assertEqual(leaving_page["recovered_s"], 14)
        self.clock.now = 15.5
        another_page = self.app.state(session=leaving_page["id"])
        self.assertEqual(another_page["time_s"], 15.5)
        self.assertEqual(another_page["remaining_s"], 44.5)
        self.action("freeze")
        self.clock.now += 20
        checkpoint = self.action("suspend")
        self.assertTrue(checkpoint["frozen"])
        self.assertEqual(checkpoint["time_s"], 15.5)
        reloaded = self.app.state(session=leaving_page["id"])
        self.assertTrue(reloaded["frozen"])
        self.assertEqual(reloaded["remaining_s"], 44.5)

    def test_poll_delta_replaces_only_changed_tail_and_no_spectra_when_unchanged(self):
        full = deepcopy(self.open("alpha"))
        cursor = full["product_cursor"]
        quiet = self.app.state(product_cursor=cursor)
        self.assertNotIn("product", quiet)
        self.assertEqual(quiet["product_delta"], {"start": 0, "segments": []})
        for duration in (1, 1, 1):
            self.acquire(duration)
            delta = self.app.state(product_cursor=cursor)
            tail = delta["product_delta"]
            full["product"]["segments"][tail["start"]:] = deepcopy(tail["segments"])
            self.assertEqual(full["product"], self.app.lab.work.product())
            cursor = delta["product_cursor"]
        self.action("start", duration=2)
        self.clock.now += 1
        delta = self.app.state(product_cursor=cursor)
        self.assertEqual(delta["product_delta"]["start"], 2)
        self.assertEqual(len(delta["product_delta"]["segments"]), 2)
        for bad in (None, "bad", "other:0:0", f"{self.app.lab.id}:999:999"):
            self.assertIn("product", self.app.state(product_cursor=bad))

    def test_unchanged_poll_does_not_scan_history_or_rewrite_draft(self):
        self.open("alpha")
        for _ in range(3):
            self.acquire(1)
        state = self.app.lab.state()

        class HistoryWithoutIteration(list):
            def __iter__(self):
                raise AssertionError("Polling must not scan historical spectra")

        product = self.app.lab.work.product()
        product["segments"] = HistoryWithoutIteration(product["segments"])
        with patch.object(self.app.store, "write", side_effect=AssertionError("Unexpected draft write")):
            quiet = self.app.state(session=state["id"], product_cursor=state["product_cursor"])
        self.assertNotIn("product", quiet)
        self.assertEqual(quiet["product_delta"], {"start": 3, "segments": []})

    def test_archive_transaction_rolls_back_all_changed_segments_and_draft_removal(self):
        self.open()
        self.acquire(1)
        self.acquire(1)
        self.action("save")
        identifier = self.app.lab.archive_id
        original = self.app.store.read(identifier)
        self.action("analysis", rate_axis=True)
        doc = deepcopy(original)
        doc["settings"]["foil_count"] = 8
        doc["product"]["segments"][0]["readings"]["counter"] = [999]
        doc["product"]["segments"][1]["readings"]["counter"] = [float("nan")]
        draft = self.app.lab.draft_id
        with self.assertRaises(ValueError):
            self.app.store.write(identifier, "archive", doc, remove=draft)
        self.assertEqual(self.app.store.read(identifier), original)
        self.assertIn(draft, [r["id"] for r in self.app.store.list()])

    def test_background_declaration_and_same_gate_nonoverlapping_segments(self):
        self.open()
        self.action("configure", values={"source_present": 0})
        self.action("start", duration=5)
        self.clock.now += 2
        self.action("configure", values={"source_present": 1})
        self.clock.now += 3
        self.app.state()
        state = self.action("analysis", background=0)
        self.assertIn("net_rate", state["readout"])
        self.assertEqual(len(state["product"]["segments"]), 2)
        self.assertEqual(state["product"]["segments"][0]["acquisition"],
                         state["product"]["segments"][1]["acquisition"])
        selected = self.action("select", index=0)
        self.assertTrue(selected["readout"]["background_reference"])
        with self.assertRaisesRegex(ValueError, "本底工况"):
            self.action("analysis", background=1)

    def test_calibration_without_measurements_uses_archived_current_settings(self):
        base = self.definitions["alpha"]
        definition = replace(base, parameters=(*base.parameters, Parameter("gain", "Gain", "", 1, 1, 2)),
                             devices=(replace(base.devices[0], calibration_parameters=("gain",)),),
                             components=(), connections=())
        self.definitions = {"alpha": definition}
        self.app = Application(self.definitions, self.folder.name, self.clock)
        self.open("alpha")
        self.action("configure", values={"gain": 2})
        self.action("calibrate", points=[0, 0, 1000, 6])
        self.action("save", exit=True)
        app = Application(self.definitions, self.folder.name, self.clock)
        restored = app.open({"archive": app.catalog()["archives"][0]["id"]})
        self.assertEqual(restored["spectrum_settings"]["gain"], 2)
        self.assertIsNotNone(restored["calibration"])
        self.assertEqual(restored["calibrated_devices"], ["mca"])


if __name__ == "__main__":
    unittest.main()
