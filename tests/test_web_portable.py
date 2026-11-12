"""Opening a portable Web lab restores saved views without resampling."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from nuclemu.catalog import describe
from nuclemu.core import Device, Experiment, Parameter, SignalOutput
from nuclemu.exchange import bind_calibration, cache_calibration, capture_session, package_bytes, load_package
from nuclemu.results import Calibration
from nuclemu.web_portable import open_portable
from nuclemu.web_store import ArchiveStore
from nuclemu.workbench import Workbench


class PortableWebTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock(side_effect=lambda settings, start, end, rng:
                          {"detector": (int(10 * (end - start)),)})
        self.definition = Experiment("test", "Test", "", (),
            (Device("counter", "counter", "Counter", input="detector"),), self.model,
            outputs=(SignalOutput("detector", "Detector"),))
        work = Workbench(definitions={"test": self.definition}, seed=42)
        work.set_output("detector", True)
        work.start(10, device="counter")
        work.advance(3)
        work.snapshot(device="counter")
        work.advance(2)
        work.snapshot(device="counter")
        self.doc = capture_session(work.session)
        ids = [item["id"] for item in self.doc["items"]]
        self.doc["analysis"] = {"counter": dict(roi=[0, 0], selected=ids[0],
            background=ids[0], reference=ids[1], energy_axis=False, rate_axis=False)}
        self.data = package_bytes(self.doc)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = ArchiveStore(self.folder.name)
        self.now = 100

    def open(self, data=None, definitions=None):
        return open_portable(self.data if data is None else data,
            {"test": self.definition} if definitions is None else definitions,
            self.store, lambda: self.now)

    def test_saved_items_and_analysis_survive_open_and_new_live_round(self):
        self.model.reset_mock()
        lab = self.open()
        self.model.assert_not_called()
        self.assertTrue(lab.portable_loaded)
        self.assertEqual(len(lab.work.session.records), 0)
        self.assertEqual([s.exposure_s for s in lab.work.session.snapshots], [3, 5])
        state = lab.state()
        self.assertFalse(state["running"])
        self.assertEqual(state["exposure_s"], 0)
        self.assertEqual((state["readout"]["counts"], state["readout"]["exposure_s"]), (30, 3))
        self.assertEqual((state["analysis"]["background"], state["analysis"]["reference"]), (0, 1))
        self.assertEqual(state["selected"], 0)
        rejected = lab.act(dict(action='select', device='counter', index=1))
        self.assertFalse(rejected)
        overlap = lab.state()
        self.assertIsNone(overlap['readout'])
        self.assertIn('同一段曝光', overlap['readout_error'])
        self.assertEqual(overlap['product']['segments'][1]['readings']['counter'], [50])
        saved = deepcopy(state["product"]["segments"])
        self.assertEqual([s["readings"]["counter"] for s in saved], [[30], [50]])
        self.assertEqual(lab.work.lab.view.changed_start_since(0), 2)
        lab.work.select(None)
        lab.work.set_output("detector", True)
        lab.work.start(1, device="counter")
        lab.work.advance(1)
        product = lab.work.product()
        self.assertEqual(product["segments"][:2], saved)
        self.assertEqual(product["segments"][2]["readings"]["counter"], [10])
        self.assertEqual(lab.work.lab.view.changed_start_since(0), 2)
        self.assertEqual([s.exposure_s for s in lab.work.session.snapshots], [3, 5])
        self.assertEqual([i["id"] for i in lab.exchange.document["items"]],
                         [i["id"] for i in self.doc["items"]])

    def test_multisegment_saved_item_is_read_as_a_whole_with_its_parts(self):
        definition = Experiment("multi", "Multi", "", (Parameter("gain", "Gain", "", 1, 1, 2),),
            (Device("counter", "counter", "Counter", input="detector"),), self.model,
            outputs=(SignalOutput("detector", "Detector"),))
        work = Workbench(definitions={"multi": definition})
        work.set_output("detector", True)
        work.start(5, device="counter")
        work.advance(2)
        work.configure({"gain": 2})
        work.advance(3)
        work.snapshot(device="counter")
        doc = capture_session(work.session)
        identity = doc["items"][0]["id"]
        doc["analysis"] = {"counter": {"selected": identity, "reference": identity, "background": identity}}
        lab = self.open(package_bytes(doc), {"multi": definition})
        self.assertEqual(len(lab.work.product()["segments"]), 2)
        self.assertEqual(lab.portable_unresolved["counter"],
                         {"background": identity})
        state = lab.state()
        self.assertEqual((state['readout']['counts'], state['readout']['exposure_s']), (50, 5))
        self.assertEqual(len(state['selected_observation']['segments']), 2)
        self.assertIsNone(lab.analysis["counter"]["reference"])
        self.assertIsNone(lab.analysis["counter"]["background"])
        copied = load_package(lab.portable_download()[2])
        for key in ('selected', 'reference', 'background'):
            self.assertEqual(copied['analysis']['counter'][key], identity)
        reopened = self.open(package_bytes(copied), {'multi': definition})
        self.assertEqual(reopened.saved_selection['counter']['reference'], identity)
        reopened.act(dict(action='analysis', device='counter', reference=None, background=None))
        reopened.act(dict(action='select', device='counter', index=None))
        changed = load_package(reopened.portable_download()[2])
        self.assertIsNone(changed['analysis']['counter']['reference'])
        self.assertIsNone(changed['analysis']['counter']['background'])
        self.assertIsNone(changed['analysis']['counter']['selected'])

    def test_explicit_saved_calibration_is_restored(self):
        model = Mock(side_effect=lambda settings, start, end, rng: {"detector": (0, 10, 0, 0)})
        definition = Experiment("spectrum", "Spectrum", "", (),
            (Device("mca", "spectrum", "MCA", 4, input="detector"),), model,
            outputs=(SignalOutput("detector", "Detector", 4),))
        work = Workbench(definitions={"spectrum": definition})
        work.set_output("detector", True)
        work.start(1, device="mca")
        work.advance(1)
        work.snapshot(device="mca")
        doc = capture_session(work.session)
        calibration = Calibration("spectrum", "mca", 4, 0, 0, 3, 6)
        identity = cache_calibration(doc, calibration)
        bind_calibration(doc, doc["items"][0]["id"], identity)
        model.reset_mock()
        lab = self.open(package_bytes(doc), {"spectrum": definition})
        model.assert_not_called()
        self.assertEqual(lab.work.lab.calibrations["mca"], calibration)
        self.assertEqual(lab.state()["readout"]["energy_MeV"], 2)

    def test_converted_package_missing_archived_observations_is_rejected(self):
        doc = deepcopy(self.doc)
        doc["legacy"] = {"archive": "historical"}
        with self.assertRaisesRegex(ValueError, "只读"):
            self.open(package_bytes(doc))

    def test_unknown_or_incompatible_course_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "课程"):
            self.open(definitions={})
        changed = Experiment("test", "Test", "", (),
            (Device("counter", "counter", "Counter", input="other"),), self.model,
            outputs=(SignalOutput("other", "Other"),))
        with self.assertRaisesRegex(ValueError, "绑定"):
            self.open(definitions={"test": changed})


if __name__ == "__main__":
    unittest.main()
