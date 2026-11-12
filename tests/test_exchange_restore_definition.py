"""Course-selected historical schemas preserve files and current load targets."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest

from nuclemu.catalog import describe
from nuclemu.core import Device, Experiment, Session, SignalOutput
from nuclemu.exchange import (capture_session, decode_measurement, export_item, load_package,
                             package_bytes, reopen_session)
from nuclemu.experiments import beta


def profiles():
    old = Experiment("port-migration", "Shared input", "", (),
        (Device("a", "counter", "A", input="first"), Device("b", "counter", "B", input="first")),
        lambda settings, start, end, rng: {"first": (round(10*(end-start)),)},
        outputs=(SignalOutput("first", "Shared"),))
    old_info = json.loads(json.dumps(describe(old)))
    current = replace(old, title="Separate inputs",
        devices=(old.devices[0], replace(old.devices[1], input="second")),
        outputs=(*old.outputs, SignalOutput("second", "Separate")),
        model=lambda settings, start, end, rng: {
            "first": (round(10*(end-start)),), "second": (round(20*(end-start)),)},
        restore_definition=lambda saved: old if saved == old_info else current)
    return old, current


def saved_old():
    old, current = profiles()
    source = Session(old)
    source.set_output("first", True)
    source.start(3)
    source.advance(3)
    source.snapshot("a")
    source.snapshot("b")
    return capture_session(source), current


class RestoredDefinitionTests(unittest.TestCase):
    def test_missing_default_output_fields_are_still_readable(self):
        doc, _ = saved_old()
        old, _ = profiles()
        for field in ("channels", "unit", "time_unit", "response"):
            doc["definition"]["outputs"][0].pop(field)
        self.assertEqual(len(reopen_session(doc, old).experiment.outputs), 1)

    def test_whole_file_restores_the_declared_historical_mode(self):
        doc, current = saved_old()
        original = deepcopy(doc)
        restored = reopen_session(load_package(package_bytes(doc)), current)
        self.assertEqual([d.input for d in restored.experiment.devices], ["first", "first"])
        self.assertEqual([s.counts for s in restored.snapshots], [(30,), (30,)])
        restored.set_output("first", True)
        restored.start(1)
        restored.advance(1)
        self.assertEqual(restored.snapshot("a").counts, (10,))
        self.assertEqual(restored.snapshot("b").counts, (10,))
        self.assertEqual(doc, original)

    def test_old_json_and_csv_load_only_fixed_prefix_into_current_mode(self):
        doc, current = saved_old()
        for fmt in ("json", "csv"):
            with self.subTest(format=fmt):
                target = Session(current)
                for item in doc["items"]:
                    device = item["document"]["snapshot"]["device"]
                    decoded = decode_measurement(export_item(doc, item["id"], fmt), current, device)
                    target.load_measurement(device, decoded.snapshot)
                self.assertIs(target.experiment, current)
                self.assertEqual([d.input for d in target.experiment.devices], ["first", "second"])
                for output in current.outputs:
                    target.set_output(output.id, True)
                target.start()
                target.advance(1)
                self.assertEqual(target.snapshot("a").counts, (40,))
                self.assertEqual(target.snapshot("b").counts, (50,))
                self.assertEqual(target.snapshot("b").exposure_s, 4)

    def test_unknown_input_and_current_target_shape_still_fail(self):
        doc, current = saved_old()
        bad = deepcopy(doc)
        bad["definition"]["devices"][1]["input"] = "unknown"
        with self.assertRaisesRegex(ValueError, "binding"):
            reopen_session(bad, current)
        identity = bad["items"][1]["id"]
        with self.assertRaisesRegex(ValueError, "target"):
            decode_measurement(bad, current, "b", identity)
        old, _ = profiles()
        wrong_shape = replace(current,
            devices=tuple(replace(d, kind="spectrum", channels=2) for d in current.devices),
            outputs=tuple(replace(o, channels=2) for o in current.outputs),
            restore_definition=lambda saved: old)
        with self.assertRaisesRegex(ValueError, "target"):
            decode_measurement(doc, wrong_shape, "b", doc["items"][1]["id"])


class BetaSavedModeTests(unittest.TestCase):
    def old_document(self):
        current = beta.EXPERIMENT
        shared = replace(current,
            devices=tuple(replace(d, input=beta.DETECTOR_OUTPUT) for d in current.devices),
            outputs=(replace(current.outputs[0], response=beta.LEGACY_SHARED_RESPONSE),),
            components=tuple(replace(p, outputs=()) for p in current.components),
            model=beta.sample_shared_counts, restore_definition=None)
        source = Session(shared, seed=187)
        source.configure({"source_present": 1})
        source.set_output(beta.DETECTOR_OUTPUT, True)
        source.start(3)
        source.advance(3)
        for d in shared.devices:
            source.snapshot(d.id)
        return capture_session(source)

    def test_real_beta_old_whole_file_reopens_and_continues_shared_input(self):
        doc = self.old_document()
        original = deepcopy(doc)
        session = reopen_session(load_package(package_bytes(doc)), beta.EXPERIMENT)
        self.assertEqual(len(session.experiment.outputs), 1)
        self.assertEqual({d.input for d in session.experiment.devices}, {beta.DETECTOR_OUTPUT})
        self.assertIn("历史", session.experiment.title)
        self.assertEqual([s.counts for s in session.snapshots], [(296,), (296,)])
        session.set_output(beta.DETECTOR_OUTPUT, True)
        session.start(1)
        session.advance(1)
        a, b = (session.snapshot(d.id) for d in session.experiment.devices)
        self.assertEqual(a.counts, b.counts)
        self.assertEqual((a.exposure_s, b.exposure_s), (1, 1))
        self.assertEqual(doc, original)
        again = reopen_session(load_package(package_bytes(capture_session(session, doc))), beta.EXPERIMENT)
        self.assertEqual(len(again.experiment.outputs), 1)

    def test_real_beta_old_single_files_prefix_current_independent_measurements(self):
        doc = self.old_document()
        original = deepcopy(doc)
        for fmt in ("json", "csv"):
            with self.subTest(format=fmt):
                target, fresh = (Session(beta.EXPERIMENT, seed=187) for _ in range(2))
                for session in (target, fresh):
                    session.configure({"source_present": 1})
                    session.set_output(beta.DETECTOR_OUTPUT, True)
                for item in doc["items"]:
                    d = item["document"]["snapshot"]["device"]
                    saved = decode_measurement(export_item(doc, item["id"], fmt), beta.EXPERIMENT, d)
                    target.load_measurement(d, saved.snapshot)
                self.assertIs(target.experiment, beta.EXPERIMENT)
                self.assertEqual(target.experiment.devices[1].input, beta.DETECTOR_OUTPUT_B)
                self.assertTrue(target.output_enabled[beta.DETECTOR_OUTPUT_B])
                fresh.start(1)
                target.start(4)
                fresh.advance(1)
                target.advance(1)
                for d in beta.EXPERIMENT.devices:
                    expected = fresh.snapshot(d.id)
                    loaded = target.snapshot(d.id)
                    self.assertEqual(loaded.counts[0]-296, expected.counts[0])
                    self.assertEqual(loaded.exposure_s, 4)
                    self.assertEqual([w.counts for w in loaded.windows[:3]], [(97,), (105,), (94,)])
                saved = load_package(package_bytes(capture_session(target)))
                self.assertEqual(reopen_session(saved, beta.EXPERIMENT).experiment.devices[1].input,
                                 beta.DETECTOR_OUTPUT_B)
                self.assertEqual(doc, original)

    def test_only_recognized_single_window_whole_file_restores_old_mode(self):
        doc = self.old_document()
        doc["definition"]["devices"] = [d for d in doc["definition"]["devices"] if d["id"] == "counter"]
        doc["items"] = [i for i in doc["items"] if i["document"]["snapshot"]["device"] == "counter"]
        doc["rounds"] = [r for r in doc["rounds"] if r["device"] == "counter"]
        doc["instruments"].pop("counter_b")
        restored = reopen_session(load_package(package_bytes(doc)), beta.EXPERIMENT)
        self.assertEqual([d.id for d in restored.experiment.devices], ["counter"])
        self.assertEqual(len(restored.experiment.outputs), 1)
        self.assertEqual(restored.snapshots[0].counts, (296,))
        bad = deepcopy(doc)
        bad["definition"]["outputs"][0]["response"] = "Unrecognized response"
        with self.assertRaisesRegex(ValueError, "signal output bindings"):
            reopen_session(load_package(package_bytes(bad)), beta.EXPERIMENT)


if __name__ == "__main__":
    unittest.main()
