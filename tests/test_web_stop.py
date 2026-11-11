"""A delayed stop owns one acquisition, while parameter edits merge by field."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Device, Experiment, Parameter, Session
from nuclemu.physics import poisson
from nuclemu.web_session import Application


class StopOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.definition = Experiment("controls", "Controls", "", (
            Parameter("gain", "Gain", "", 1, 0, 9, True),
            Parameter("threshold", "Threshold", "", 1, 0, 9, True)),
            (Device("counter", "counter", "Counter"),),
            lambda settings, start, end, rng: {"counter": (
                poisson((10 * settings["gain"] + settings["threshold"]) * (end - start), rng),)})
        self.open()

    def open(self):
        self.app = Application({"controls": self.definition}, self.folder.name, clock=lambda: self.now)
        return self.app.open({"experiment": "controls", "seed": 187})

    def call(self, action, **data):
        return self.app.request("/api/action", dict(session=self.app.lab.id, action=action, **data))

    def test_old_stop_does_not_settle_or_stop_the_next_gate_and_valid_stop_closes_its_tail(self):
        first = self.call("start", duration=10)["active_acquisition"]
        self.now = .25
        self.call("stop", acquisition=first)
        second = self.call("start", duration=10)["active_acquisition"]
        self.assertNotEqual(second, first)
        self.now = .5
        before = deepcopy(self.app.state())
        draft = self.app.store.read(self.app.lab.draft_id)
        rng = self.app.lab.work.session._rng.getstate()
        self.now = 1
        with self.assertRaisesRegex(ValueError, "采集轮次"):
            self.call("stop", acquisition=first)
        self.assertEqual(self.app.lab.time_s(), .5)
        self.assertEqual(self.app.lab.work.session.remaining_s, before["remaining_s"])
        self.assertEqual(self.app.lab.work.session.active_acquisition, second)
        self.assertEqual(self.app.lab.work.product(), before["product"])
        self.assertEqual(self.app.lab.work.session._rng.getstate(), rng)
        self.assertEqual(self.app.store.read(self.app.lab.draft_id), draft)
        stopped = self.call("stop", acquisition=second)
        self.assertIsNone(stopped["active_acquisition"])
        self.assertFalse(stopped["running"])
        self.assertEqual(stopped["measurement_end_s"], 1)
        rows = self.app.lab.work.session.records
        self.assertEqual([(r.acquisition, r.exposure_s) for r in rows], [(first, .25), (second, .75)])
        reference = Session(self.definition, seed=187)
        reference.start(10)
        reference.advance(.25)
        reference.stop()
        reference.start(10)
        reference.advance(.75)
        reference.stop()
        self.assertEqual(rows, reference.records)

    def test_missing_invalid_or_finished_acquisition_is_rejected_before_clock_advance(self):
        acquisition = self.call("start", duration=2)["active_acquisition"]
        self.now = .25
        for invalid in (None, True, "1", 0, acquisition + 1):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "采集轮次"):
                self.call("stop", acquisition=invalid)
            self.assertEqual(self.app.lab.time_s(), 0)
            self.assertEqual(self.app.lab.work.session.records, [])
        with self.assertRaisesRegex(ValueError, "采集轮次"):
            self.call("stop")
        self.call("stop", acquisition=acquisition)
        self.now = 1
        with self.assertRaisesRegex(ValueError, "采集轮次"):
            self.call("stop", acquisition=acquisition)
        self.assertEqual(self.app.lab.time_s(), .25)

    def test_timed_completion_during_valid_stop_sync_does_not_create_extra_exposure(self):
        acquisition = self.call("start", duration=.25)["active_acquisition"]
        self.now = 1
        state = self.call("stop", acquisition=acquisition)
        self.assertIsNone(state["active_acquisition"])
        self.assertEqual(state["time_s"], 1)
        self.assertEqual(state["measurement_end_s"], .25)
        self.assertEqual(len(self.app.lab.work.session.records), 1)
        self.assertEqual(self.app.lab.work.session.records[0].exposure_s, .25)

    def test_configure_splits_conditions_without_replacing_the_active_acquisition(self):
        acquisition = self.call("start", duration=2)["active_acquisition"]
        self.now = .25
        changed = self.call("configure", values={"gain": 2})
        self.assertEqual(changed["active_acquisition"], acquisition)
        self.assertEqual(changed["remaining_s"], 1.75)
        self.now = .375
        changed = self.call("configure", values={"threshold": 3})
        self.assertEqual(changed["active_acquisition"], acquisition)
        self.assertEqual(changed["settings"], {"gain": 2, "threshold": 3})
        self.now = .5
        self.call("stop", acquisition=acquisition)
        rows = self.app.lab.work.session.records
        self.assertEqual([row.acquisition for row in rows], [acquisition] * 3)
        self.assertEqual([(row.settings["gain"], row.settings["threshold"]) for row in rows],
                         [(1, 1), (2, 1), (2, 3)])
        self.assertEqual(sum(row.exposure_s for row in rows), .5)
        with self.assertRaises(AttributeError):
            self.app.lab.work.session.active_acquisition = 99

    def test_disjoint_configure_subsets_merge_with_or_without_an_intervening_poll(self):
        for poll in (False, True):
            with self.subTest(poll=poll):
                self.open()
                # A edits gain locally; B changes threshold before A submits.
                self.call("configure", values={"threshold": 3})
                if poll:
                    self.app.state()
                state = self.call("configure", values={"gain": 2})
                self.assertEqual(state["settings"], {"gain": 2, "threshold": 3})
                # An explicit same-field edit retains ordinary last-application semantics.
                self.call("configure", values={"gain": 4})
                state = self.call("configure", values={"gain": 2})
                self.assertEqual(state["settings"], {"gain": 2, "threshold": 3})
                self.call("save")
                saved = self.app.store.read(self.app.lab.archive_id)
                self.assertEqual(saved["settings"], {"gain": 2, "threshold": 3})


if __name__ == "__main__":
    unittest.main()
