"""Loading saved measurements starts a fresh idle round, never a resampling."""

from dataclasses import replace
from math import floor
import unittest

from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.results import configuration_document, snapshot_product


def definition():
    def pulses(settings, start, end, rng):
        return {"out": (floor(end*10)-floor(start*10),)}
    return Experiment("reopen", "Reopen", "", (Parameter("x", "X", "", 0, 0, 10),),
                      (Device("a", "counter", "A", input="out"),), pulses,
                      outputs=(SignalOutput("out", "Output"),))


class ReopenTests(unittest.TestCase):
    def saved(self):
        session = Session(definition())
        session.set_output("out", True)
        session.start(device="a")
        session.advance(3)
        session.snapshot("a")
        session.advance(2)
        session.configure({"x": 2})
        return session

    def open(self, source, **overrides):
        args = dict(settings=source.settings, time_s=source.time_s, rounds=source.rounds,
                    snapshots=source.snapshots, configuration_history=source.configuration_history)
        args.update(overrides)
        return Session.reopen(source.experiment, source.seed, **args)

    def test_saved_three_second_spectrum_with_five_second_round_stays_three(self):
        source = self.saved()
        reopened = self.open(source)
        self.assertEqual(reopened.records, [])
        self.assertFalse(reopened.running)
        self.assertFalse(reopened.clock_running)
        self.assertEqual(reopened.instrument("a").exposure_s, 0)
        self.assertEqual(reopened.instrument("a").counts, (0,))
        self.assertEqual(reopened.rounds[0].exposure_s, 5)
        self.assertEqual(reopened.snapshots[0].counts, (30,))
        self.assertEqual(reopened.snapshots[0].exposure_s, 3)
        reopened.advance(100)
        self.assertEqual(reopened.time_s, 5)
        reopened.set_output("out", True)
        reopened.start(device="a")
        reopened.advance(1)
        self.assertEqual(reopened.instrument("a").acquisition, 2)
        self.assertEqual(reopened.instrument("a").counts, (10,))
        self.assertEqual(reopened.snapshot("a").id, 2)
        self.assertEqual(reopened.snapshots[0].counts, (30,))
        self.assertEqual(reopened.settings, {"x": 2})
        history = configuration_document(reopened)["history"]
        self.assertIn({"out": False}, [c["values"] for c in history if c["kind"] == "output"])

    def test_reopen_validates_canonical_settings_without_live_adapter(self):
        source = self.saved()
        def adapter(values):
            raise AssertionError("Archive loading must not call live-command conversion")
        lab = replace(source.experiment, normalize_settings=adapter)
        restored = Session.reopen(lab, settings={"x": 2})
        self.assertEqual(restored.settings, {"x": 2})
        with self.assertRaisesRegex(ValueError, "canonical"):
            Session.reopen(lab, settings={"legacy": 2})
        with self.assertRaises(ValueError):
            Session.reopen(lab, settings={"x": 99})

    def test_reopen_restores_targets_as_idle_settings_not_elapsed_measurement(self):
        source = self.saved()
        reopened = self.open(source, acquisition_settings={"a": dict(duration_s=3, count_limit=100, window_s=2)})
        before = reopened.instrument("a")
        self.assertEqual((before.duration_s, before.count_limit, before.window_s), (3, 100, 2))
        self.assertFalse(before.running)
        self.assertEqual(before.exposure_s, 0)
        reopened.set_output("out", True)
        reopened.start(device="a")
        reopened.advance(3)
        self.assertEqual(reopened.instrument("a").exposure_s, 3)
        self.assertEqual(reopened.instrument("a").counts, (30,))

    def test_corrupt_exposure_counts_binding_and_sequences_are_rejected(self):
        source = self.saved()
        item, = source.snapshots
        for bad in (replace(item, exposure_s=4), replace(item, counts=(31,)),
                    replace(item, counts=(30.0,)), replace(item, device="missing"),
                    replace(item, acquisition=2)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.open(source, snapshots=(bad,))
        with self.assertRaisesRegex(ValueError, "sequence"):
            change = replace(source.configuration_history[0], sequence=2)
            self.open(source, configuration_history=(change,))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.open(source, rounds=source.rounds*2)

    def test_failed_snapshot_writer_keeps_gate_and_data_and_no_new_cache(self):
        source = self.saved()
        before = source.snapshots
        def failed(item):
            source.advance(1)
            self.assertEqual(item.counts, (50,))
            raise OSError("snapshot failed")
        with self.assertRaisesRegex(OSError, "snapshot failed"):
            source.snapshot("a", writer=failed)
        self.assertEqual(source.snapshots, before)
        self.assertTrue(source.instrument("a").running)
        self.assertEqual(source.instrument("a").counts, (60,))
        self.assertEqual(source.snapshot("a").id, 2)


if __name__ == "__main__":
    unittest.main()
