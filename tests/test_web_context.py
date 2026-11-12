"""Delayed commands must keep the exit round and spectrum the user actually saw."""

from copy import deepcopy
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.core import Device, Experiment, Parameter
from nuclemu.results import Calibration
from nuclemu.web_session import Application
from tests.legacy_web_fixture import legacy_course


class WebContextTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.app = Application(discover(), self.folder.name, lambda: self.now)

    def call(self, action, **data):
        return self.app.request("/api/action", dict(session=self.app.lab.id, action=action, **data))

    def open(self, **data):
        state = self.app.open(dict(experiment="beta", seed=42, **data))
        self.call("output", output="beta_detector", enabled=True)
        return state

    def open_legacy(self):
        definition = legacy_course("beta")
        self.app = Application({definition.id: definition}, self.folder.name, lambda: self.now)
        return self.app.open({"experiment": definition.id, "seed": 42})

    def test_old_round_cannot_touch_resumed_measurements_draft_or_a_new_confirmation(self):
        self.open_legacy()
        self.call("start", duration=60)
        self.now = 14.5
        first = self.call("freeze")["confirmation_id"]
        self.assertEqual(self.call("freeze")["confirmation_id"], first)
        self.call("continue", confirmation_id=first)
        self.now += 1
        resumed = deepcopy(self.app.state())
        draft = self.app.store.read(self.app.lab.draft_id)
        self.now += 10
        for action, options in (("continue", {}), ("discard", {}), ("save", {"exit": True})):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "已过期"):
                self.call(action, confirmation_id=first, **options)
            self.assertEqual(self.app.lab.time_s(), resumed["time_s"])
            self.assertEqual(self.app.lab.work.product(), resumed["product"])
            self.assertEqual(self.app.store.read(self.app.lab.draft_id), draft)
        second = self.call("freeze")["confirmation_id"]
        self.assertNotEqual(second, first)
        with self.assertRaisesRegex(ValueError, "已过期"):
            self.call("continue", confirmation_id=first)
        self.assertEqual(self.app.lab.confirmation_id, second)
        self.assertTrue(self.app.lab.frozen)
        with self.assertRaisesRegex(ValueError, "退出确认"):
            self.call("save")

    def test_course_confirmation_keeps_measurement_live_without_writing_a_draft(self):
        self.open()
        self.call("start", device="counter", duration=60)
        self.now = 14.5
        token = self.call("freeze")["confirmation_id"]
        self.assertEqual(self.app.catalog()["drafts"], [])
        self.call("continue", confirmation_id=token)
        self.now += 1
        state = self.app.state()
        self.assertTrue(state["running"])
        self.assertEqual(state["remaining_s"], 44.5)
        self.assertEqual(self.app.catalog()["drafts"], [])
        with self.assertRaisesRegex(ValueError, "已过期"):
            self.call("discard", confirmation_id=token)
        self.assertEqual(self.app.catalog()["drafts"], [])

    def test_missing_or_boolean_confirmation_is_not_a_valid_round(self):
        self.open()
        self.call("freeze")
        for token in (None, True, "1", 999):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "已过期"):
                self.call("discard", confirmation_id=token)
        self.assertTrue(self.app.lab.frozen)

    def test_save_and_discard_failures_preserve_the_same_confirmation_for_retry(self):
        for finish in ("save", "discard"):
            with self.subTest(finish=finish):
                self.app = Application(discover(), self.folder.name, lambda: self.now)
                self.open_legacy()
                self.call("start", duration=60)
                self.now += 14.5
                token = self.call("freeze")["confirmation_id"]
                lab = self.app.lab
                rng = lab.work.session._rng.getstate()
                options = {"exit": True} if finish == "save" else {}
                method = "write" if finish == "save" else "remove"
                with patch.object(self.app.store, method, side_effect=sqlite3.OperationalError("locked")):
                    with self.assertRaises(sqlite3.Error):
                        self.call(finish, confirmation_id=token, **options)
                self.assertIs(self.app.lab, lab)
                self.assertEqual(lab.confirmation_id, token)
                self.assertEqual(lab.work.session.remaining_s, 45.5)
                self.assertEqual(lab.work.session._rng.getstate(), rng)
                self.assertIsNone(self.call(finish, confirmation_id=token, **options))
                self.assertIsNone(self.app.lab)
                self.assertIsNone(lab.confirmation_id)

    def test_completed_round_cannot_delete_a_new_session_or_its_draft(self):
        opened = self.open_legacy()
        token = self.call("freeze")["confirmation_id"]
        self.call("discard", confirmation_id=token)
        self.app.open({"experiment": "legacy_beta", "seed": 42})
        self.call("start", duration=2)
        self.now = 1
        self.app.state()
        draft = self.app.store.read(self.app.lab.draft_id)
        new_id = self.app.lab.id
        for session in (opened["id"], new_id):
            with self.subTest(session=session), self.assertRaises(ValueError):
                self.app.request("/api/action", dict(session=session, action="discard", confirmation_id=token))
        self.assertEqual(self.app.lab.id, new_id)
        self.assertEqual(self.app.store.read(self.app.lab.draft_id), draft)

    def spectra(self):
        definition = Experiment("two", "Two spectra", "", (Parameter("gain", "Gain", "", 1, 1, 2),),
            (Device("left", "spectrum", "Left", 8, ("gain",)),
             Device("right", "spectrum", "Right", 8, ("gain",))),
            lambda settings, start, end, rng: {"left": (0, 3, 0, 0, 0, 0, 0, 0),
                                              "right": (0, 0, 0, 5, 0, 0, 0, 0)})
        self.app = Application({definition.id: definition}, self.folder.name, lambda: self.now)
        self.app.open({"experiment": "two", "seed": 42})
        for gain in (1, 2):
            self.call("configure", values={"gain": gain})
            self.call("start", duration=1)
            self.now += 1
            self.app.state()

    def test_calibration_context_rejects_another_device_record_and_applicable_gain(self):
        self.spectra()
        self.call("select", device="left", index=0)
        context = deepcopy(self.app.lab.state()["calibration_context"])
        self.assertEqual(context, {"device": "left", "selected": 0, "record_id": None, "settings": {"gain": 1}})
        calibration = Calibration("two", "left", 8, 0, 0, 7, 7, conditions=(("gain", 1),))
        for action, payload in (("calibrate", {"points": [0, 0, 7, 7]}),
                                ("load_calibration", {"calibration": calibration.document()})):
            self.call("device", device="right")
            before = deepcopy(self.app.lab.analysis)
            self.now += 1
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "刻度所用"):
                self.call(action, calibration_context=context, **payload)
            self.assertEqual(self.app.lab.work.lab.calibrations, {})
            self.assertEqual(self.app.lab.analysis, before)
            self.assertEqual(self.app.lab.time_s(), self.now)
            self.call("device", device="left")
        self.call("select", device="left", index=1)
        with self.assertRaisesRegex(ValueError, "刻度所用"):
            self.call("calibrate", points=[0, 0, 7, 7], calibration_context=context)
        self.assertEqual(self.app.lab.work.lab.calibrations, {})

    def test_historical_calibration_uses_its_record_conditions_not_current_gain(self):
        self.spectra()
        self.call("select", device="left", index=0)
        context = deepcopy(self.app.lab.state()["calibration_context"])
        self.assertEqual(self.app.lab.settings()["gain"], 2)
        state = self.call("calibrate", points=[0, 0, 7, 7], calibration_context=context)
        self.assertEqual(state["readout"]["energy_MeV"], 1)
        self.assertEqual(state["calibration"]["conditions"], (("gain", 1.0),))
        state = self.call("select", device="left", index=1)
        self.assertIsNone(state["calibration"])

    def test_analysis_device_rejects_stale_roi_without_changing_either_instrument(self):
        self.spectra()
        self.call("analysis", device="left", roi=[1, 2])
        self.call("device", device="right")
        before = deepcopy(self.app.lab.analysis)
        with self.assertRaisesRegex(ValueError, "所用设备"):
            self.call("analysis", roi=[2, 3])
        self.assertEqual(self.app.lab.analysis, before)
        with self.assertRaisesRegex(ValueError, "所用设备已改变"):
            self.call("analysis", device="left", roi=[2, 3])
        self.assertEqual(self.app.lab.analysis, before)
        state = self.call("analysis", device="right", roi=[2, 3])
        self.assertEqual(state["analysis"]["roi"], [2, 3])
        self.assertEqual(self.app.lab.analysis["left"]["roi"], [1, 2])

    def test_no_record_context_is_invalid_after_gain_change_or_first_completed_spectrum(self):
        self.spectra()
        # Reopen a new empty session using the same declared instruments.
        definition = self.app.lab.work.session.experiment
        self.app = Application({"two": definition}, self.folder.name, lambda: self.now)
        state = self.app.open({"experiment": "two"})
        context = deepcopy(state["calibration_context"])
        self.assertIsNone(context["selected"])
        self.call("configure", values={"gain": 2})
        with self.assertRaisesRegex(ValueError, "刻度所用"):
            self.call("calibrate", points=[0, 0, 7, 7], calibration_context=context)
        context = deepcopy(self.app.lab.state()["calibration_context"])
        self.call("start", duration=1)
        self.now += 1
        # The new record closes during sync before the context is checked.
        with self.assertRaisesRegex(ValueError, "刻度所用"):
            self.call("calibrate", points=[0, 0, 7, 7], calibration_context=context)
        self.assertEqual(self.app.lab.work.lab.calibrations, {})

    def test_open_rejoins_only_the_same_live_or_archived_identity_without_unfreezing(self):
        opened = self.open_legacy()
        token = self.call("freeze")["confirmation_id"]
        repeated = self.app.open({"experiment": "legacy_beta"})
        self.assertEqual(repeated["id"], opened["id"])
        self.assertEqual(repeated["confirmation_id"], token)
        self.assertTrue(repeated["frozen"])
        for other in ({"experiment": "alpha"}, {"experiment": "legacy_beta", "seed": 1},
                      {"archive": opened["id"]}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                self.app.open(other)
        self.call("save", exit=True, confirmation_id=token)
        archive = self.app.catalog()["archives"][0]["id"]
        viewed = self.app.open({"archive": archive})
        self.assertEqual(self.app.open({"archive": archive})["id"], viewed["id"])
        for other in ({"experiment": "legacy_beta"}, {"draft": archive}, {"archive": "other"}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                self.app.open(other)

    def test_open_rejoins_the_same_recovered_draft_without_starting_a_live_session(self):
        self.open_legacy()
        self.call("start", duration=2)
        self.now = 1
        self.app.state()
        draft = self.app.lab.draft_id
        self.app = Application(discover(), self.folder.name, lambda: self.now)
        recovered = self.app.open({"draft": draft})
        repeated = self.app.open({"draft": draft})
        self.assertEqual(repeated["id"], recovered["id"])
        self.assertTrue(repeated["readonly"])
        self.assertFalse(repeated["running"])
        self.assertEqual(repeated["recovered_s"], 1)
        for other in ({"experiment": "beta"}, {"archive": draft}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                self.app.open(other)


if __name__ == "__main__":
    unittest.main()
