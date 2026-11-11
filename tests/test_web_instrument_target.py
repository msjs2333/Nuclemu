"""Instrument-local commands cannot follow another page's device switch."""

from copy import deepcopy
import json
from math import sqrt
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover
from nuclemu.core import Device, Experiment, Parameter
from nuclemu.web_session import Application


class InstrumentTargetTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        rates = ((2, 4), (8, 12), (4, 2))

        def model(settings, start, end, rng):
            left, right = rates[settings["phase"]]
            return {"left": (int(left * (end - start)),), "right": (int(right * (end - start)),)}

        definition = Experiment("two", "Two counters", "", (Parameter("phase", "Phase", "", 0, 0, 2, True),),
                                (Device("left", "counter", "Left"), Device("right", "counter", "Right")), model)
        self.definitions = {"two": definition}
        self.app = Application(self.definitions, self.folder.name, clock=lambda: self.now)
        self.app.open({"experiment": "two"})

    def call(self, action, **data):
        return self.app.request("/api/action", dict(session=self.app.lab.id, action=action, **data))

    def collect(self):
        for phase, duration in ((0, 1), (1, 2), (2, 1)):
            self.call("configure", values={"phase": phase})
            self.call("start", duration=duration)
            self.now += duration
            self.app.state()
        self.call("analysis", device="left", background=0, reference=2, rate_axis=True)
        self.call("select", device="left", index=1)
        left = deepcopy(self.app.lab.state()["readout"])
        self.call("device", device="right")
        self.call("analysis", device="right", background=2, reference=0)
        self.call("select", device="right", index=1)
        right = deepcopy(self.app.lab.state()["readout"])
        self.assertEqual((left["net_rate"], left["uncertainty"]), (6, sqrt(6)))
        self.assertEqual((right["net_rate"], right["uncertainty"]), (10, sqrt(8)))
        return left, right

    def test_all_analysis_fields_and_history_selection_reject_stale_or_missing_target(self):
        left, right = self.collect()
        self.call("save")
        archive_id = self.app.lab.archive_id
        saved = deepcopy(self.app.store.read(archive_id))
        analysis = deepcopy(self.app.lab.analysis)
        for field, value in (("roi", [0, 0]), ("reference", 2), ("background", 0),
                             ("energy_axis", True), ("rate_axis", True)):
            for target in ({}, {"device": "left"}, {"device": "missing"}, {"device": None}):
                with self.subTest(field=field, target=target), self.assertRaises(ValueError):
                    self.call("analysis", **{field: value}, **target)
                self.assertEqual(self.app.lab.analysis, analysis)
                self.assertEqual(self.app.lab.work.lab.background, 2)
                self.assertEqual(self.app.lab.work.lab.selected, 1)
                self.assertEqual(self.app.lab.state()["readout"], right)
                self.assertEqual(self.app.store.read(archive_id), saved)
        for index in (0, None):
            for target in ({}, {"device": "left"}, {"device": None}):
                with self.subTest(index=index, target=target), self.assertRaises(ValueError):
                    self.call("select", index=index, **target)
                self.assertEqual(self.app.lab.analysis, analysis)
                self.assertEqual(self.app.lab.state()["readout"], right)
        # A rejected command must not poison the next properly targeted command.
        state = self.call("analysis", device="right", background=0)
        self.assertEqual(state["readout"]["net_rate"], 8)
        self.assertEqual(self.app.lab.analysis["left"], analysis["left"])
        self.call("device", device="left")
        self.assertEqual(self.app.lab.state()["readout"], left)
        self.call("select", device="left", index=None)
        self.assertIsNone(self.app.lab.analysis["left"]["selected"])
        self.assertEqual(self.app.lab.analysis["right"]["selected"], 1)

    def test_saved_analysis_background_and_selected_records_survive_rejection_and_reopen(self):
        left, right = self.collect()
        before = deepcopy(self.app.lab.analysis)
        for action, data in (("analysis", {"background": 0}), ("select", {"index": 0})):
            with self.assertRaises(ValueError):
                self.call(action, device="left", **data)
        self.call("save")
        identifier = self.app.lab.archive_id
        reader = Application(self.definitions, self.folder.name, clock=lambda: self.now)
        state = reader.open({"archive": identifier})
        self.assertEqual(reader.lab.analysis, before)
        self.assertEqual(state["readout"], right)
        self.assertEqual(state["selected"], 1)
        state = reader.request("/api/action", dict(session=reader.lab.id, action="device", device="left"))
        self.assertEqual(state["readout"], left)
        self.assertEqual(state["analysis"]["background"], 0)
        self.assertEqual(state["selected"], 1)

    def test_one_instrument_legacy_commands_work_but_explicit_wrong_device_is_rejected(self):
        self.app = Application(discover(), self.folder.name, clock=lambda: self.now)
        self.app.open({"experiment": "beta"})
        self.call("configure", values={"source_present": 0})
        self.call("start", duration=1)
        self.now = 1
        self.app.state()
        state = self.call("analysis", roi=[0, 0], reference=0, background=0,
                          energy_axis=True, rate_axis=True)
        self.assertEqual(state["analysis"]["reference"], 0)
        self.assertTrue(state["analysis"]["rate_axis"])
        self.call("select", index=0)
        before = deepcopy(self.app.lab.analysis)
        for action, data in (("analysis", {"background": None}), ("select", {"index": None})):
            for device in (None, "left", ""):
                with self.subTest(action=action, device=device), self.assertRaises(ValueError):
                    self.call(action, device=device, **data)
                self.assertEqual(self.app.lab.analysis, before)

    def test_session_controls_and_explicit_other_device_exports_keep_their_existing_scope(self):
        self.collect()
        # Export already has an explicit device and can target an unselected instrument.
        content = self.app.request("/api/export", dict(session=self.app.lab.id, device="left",
            kind="measurement", format="json", indices=[1]))
        product = json.loads(content)
        self.assertEqual(product["segments"][0]["readings"], {"left": [16]})
        self.call("configure", values={"phase": 2})
        self.call("speed", speed=2)
        self.call("start", duration=1)
        self.call("pause", paused=True)
        self.now += 5
        self.assertEqual(self.app.state()["remaining_s"], 1)
        self.call("pause", paused=False)
        self.call("stop")
        self.assertFalse(self.app.lab.work.session.running)


if __name__ == "__main__":
    unittest.main()
