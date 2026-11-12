"""Independent acquisition checks for provisional saves and apparatus bindings."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe, discover
from nuclemu.core import Device, Experiment, Session
from nuclemu.results import collect, save_product, snapshot_product
from legacy_web_fixture import legacy_course


class SessionPreviewTests(unittest.TestCase):
    def test_repeated_preview_matches_stop_without_consuming_original_rng(self):
        for name in ("alpha", "beta"):
            with self.subTest(experiment=name):
                session = Session(legacy_course(name), seed=187)
                session.start(2.25)
                session.advance(1.375)
                records = session.records.copy()
                rng_state = session._rng.getstate()
                first = session.preview_stop()
                self.assertEqual(first, session.preview_stop())
                self.assertEqual(session.records, records)
                self.assertEqual(session._rng.getstate(), rng_state)
                self.assertTrue(session.running)
                self.assertEqual(session.time_s, 1.375)
                self.assertEqual(session.remaining_s, 0.875)
                self.assertEqual((first.start_s, first.end_s), (1, 1.375))
                with self.assertRaises(TypeError):
                    first.readings[next(iter(first.readings))] = (0,)
                session.stop()
                self.assertEqual(session.records, [*records, first])
                self.assertNotEqual(session._rng.getstate(), rng_state)
                self.assertIsNone(session.remaining_s)

    def test_failed_real_save_can_continue_to_the_original_timed_endpoint(self):
        for name in ("alpha", "beta"):
            with self.subTest(experiment=name):
                definition = legacy_course(name)
                session = Session(definition, seed=442)
                reference = Session(definition, seed=442)
                for item in (session, reference):
                    item.advance(5)
                    item.start(2.25)
                    item.advance(1.375)
                provisional = session.preview_stop()
                product = collect(definition, [*session.records, provisional], session.seed)
                with TemporaryDirectory() as directory:
                    destination = Path(directory) / "missing" / "measurement.json"
                    with self.assertRaises(OSError):
                        save_product(destination, product)
                self.assertEqual(session.time_s, reference.time_s)
                self.assertEqual(session.remaining_s, reference.remaining_s)
                self.assertEqual(session._rng.getstate(), reference._rng.getstate())
                self.assertEqual(session.records, reference.records)
                for item in (session, reference):
                    item.advance(2)
                    self.assertFalse(item.running)
                    self.assertIsNone(item.remaining_s)
                    self.assertEqual(item.records[-1].end_s, 7.25)
                    self.assertEqual(sum(r.exposure_s for r in item.records), 2.25)
                    self.assertEqual(item.time_s, 8.375)
                    # Another acquisition also observes the unchanged RNG stream.
                    item.start(0.25)
                    item.advance(0.25)
                self.assertEqual(session.records, reference.records)

    def test_failed_preview_model_or_validation_leaves_the_live_session_untouched(self):
        for failure in ("exception", "binding", "counts"):
            with self.subTest(failure=failure):
                fault = [False]

                def model(settings, start, end, rng):
                    count = rng.randrange(1000000)
                    if fault[0]:
                        if failure == "exception":
                            raise RuntimeError("injected acquisition failure")
                        if failure == "counts":
                            return {"counter": (-1,)}
                        return {"wrong-device": (count,)}
                    return {"counter": (count,)}

                definition = Experiment("preview", "Preview", "", (),
                                        (Device("counter", "counter", "Counter"),), model)
                session, reference = Session(definition, seed=42), Session(definition, seed=42)
                for item in (session, reference):
                    item.start(2.25)
                    item.advance(1.375)
                fault[0] = True
                with self.assertRaisesRegex(ValueError, "sampling"):
                    session.preview_stop()
                self.assertEqual(session.records, reference.records)
                self.assertEqual(session._rng.getstate(), reference._rng.getstate())
                self.assertEqual(session.remaining_s, 0.875)
                self.assertTrue(session.running)
                self.assertEqual(session.time_s, 1.375)
                fault[0] = False
                for item in (session, reference):
                    item.advance(1)
                self.assertEqual(session.records, reference.records)
                self.assertEqual(session.records[-1].end_s, 2.25)

    def test_empty_preview_and_remaining_time_lifecycle(self):
        session = Session(legacy_course("beta"))
        self.assertIsNone(session.preview_stop())
        self.assertIsNone(session.remaining_s)
        session.start()
        self.assertIsNone(session.preview_stop())
        self.assertIsNone(session.remaining_s)
        session.advance(1)
        self.assertIsNone(session.preview_stop())
        session.stop()
        session.start(1.25)
        self.assertEqual(session.remaining_s, 1.25)
        session.advance(0.375)
        session.set("foil_count", 4)
        self.assertEqual(session.remaining_s, 0.875)
        self.assertIsNone(session.preview_stop())
        session.advance(0.25)
        preview = session.preview_stop()
        self.assertEqual(preview.settings["foil_count"], 4)
        self.assertEqual((preview.start_s, preview.end_s), (1.375, 1.625))
        session.advance(1)
        self.assertFalse(session.running)
        self.assertIsNone(session.preview_stop())
        self.assertIsNone(session.remaining_s)
        self.assertEqual(session.records[-1].end_s, 2.25)

    def test_independent_courses_use_completed_snapshots_and_failed_save_keeps_live_sampling(self):
        for name, device in (("alpha", "mca"), ("beta", "counter")):
            with self.subTest(experiment=name):
                definition = discover()[name]
                session, reference = Session(definition, seed=442), Session(definition, seed=442)
                for item in (session, reference):
                    self.assertFalse(any(item.output_enabled.values()))
                    item.set_output(definition.devices[0].input, True)
                    item.advance(5)
                    item.start(2.25, device=device)
                    item.advance(1.375)
                state = session.instrument(device)
                records = session.records.copy()
                rng = session._rng.getstate()
                with self.assertRaisesRegex(ValueError, "Independent instruments"):
                    session.preview_stop()
                readable = session.snapshot(device, cache=False)
                self.assertEqual(readable.exposure_s, 1)
                self.assertEqual(state.exposure_s, 1.375)
                self.assertEqual(state.remaining_s, .875)
                self.assertEqual(session._rng.getstate(), rng)
                self.assertEqual(session.records, records)
                with TemporaryDirectory() as directory:
                    destination = Path(directory) / "missing" / "measurement.json"
                    def writer(snapshot):
                        save_product(destination, snapshot_product(definition, snapshot, session.seed))
                    with self.assertRaises(OSError):
                        session.snapshot(device, writer=writer)
                self.assertEqual(session.snapshots, ())
                self.assertEqual(session.instrument(device), reference.instrument(device))
                self.assertEqual(session.records, reference.records)
                self.assertEqual(session._rng.getstate(), reference._rng.getstate())
                for item in (session, reference):
                    item.advance(2)
                    self.assertFalse(item.instrument(device).running)
                    self.assertEqual(item.instrument(device).exposure_s, 2.25)
                self.assertEqual(session.records, reference.records)
                self.assertEqual(session._rng.getstate(), reference._rng.getstate())


class ApparatusIntegrationTests(unittest.TestCase):
    def test_controls_and_signal_links_reach_the_same_real_instrument(self):
        for name, controls in (("alpha", {"foil_spec_um": 1, "foil_count": 5}),
                               ("beta", {"source_present": 0, "foil_count": 4})):
            with self.subTest(experiment=name):
                definition = discover()[name]
                entry = describe(definition)
                parts = {p["id"]: p for p in entry["components"]}
                session, reference = Session(definition, seed=187), Session(definition, seed=187)
                for key, value in controls.items():
                    owner = next(p for p in parts.values() if key in p["parameters"])
                    session.set(next(k for k in owner["parameters"] if k == key), value)
                    reference.set(key, value)
                signal = next(link for link in entry["connections"] if link["kind"] == "signal")
                detector = parts[signal["source"]]
                instrument = parts[signal["target"]]
                device = instrument["device"]
                declared = next(d for d in entry["devices"] if d["id"] == device)
                self.assertEqual(detector["output"], declared["input"])
                self.assertIsNone(detector["device"])
                session.set_output(detector["output"], True)
                reference.set_output(definition.devices[0].input, True)
                for item in (session, reference):
                    item.start(1.25, device=device)
                    item.advance(0.375)
                session.stop(device=device)
                reference.stop(device=device)
                self.assertEqual(len(session.records[0].readings[device]), declared["channels"])
                self.assertEqual(session.snapshot(device, cache=False).exposure_s, .375)
                self.assertTrue(all(set(row.readings) == {device} for row in session.records))
                self.assertEqual(session.records, reference.records)
                # Describe is catalogue metadata and must not sample or run a gate.
                self.assertEqual(entry, describe(definition))

    def test_legacy_multiple_instruments_keep_distinct_bindings(self):
        # Load an actual old-style external module, with device-id readings and
        # no independent-output metadata, rather than modifying a new course.
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy_counters.py"
            path.write_text(
                "from nuclemu.core import Device, Experiment\n"
                "def measure(settings, start, end, rng): return {'left': (3,), 'right': (7,)}\n"
                "EXPERIMENT = Experiment('two-counters', 'Two counters', '', (), "
                "(Device('left','counter','Left'), Device('right','counter','Right')), measure)\n",
                encoding="utf-8")
            definition = discover([directory])["two-counters"]
        entry = describe(definition)
        bindings = [p["device"] for p in entry["components"] if p["device"]]
        self.assertEqual(bindings, ["left", "right"])
        session = Session(definition)
        session.start()
        session.advance(0.25)
        preview = session.preview_stop()
        self.assertEqual([preview.readings[key][0] for key in bindings], [3, 7])
        session.stop()
        self.assertEqual(session.records, [preview])


if __name__ == "__main__":
    unittest.main()
