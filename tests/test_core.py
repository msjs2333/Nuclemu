"""Contracts for modular discovery and the single-clock acquisition model."""

from dataclasses import replace
from pathlib import Path
from random import Random
from statistics import mean, variance
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe, discover
from nuclemu.core import Component, Connection, Device, Experiment, Parameter, Session
from nuclemu.physics import AluminumFoil, poisson


def split_counter(settings, start, end, rng):
    n = poisson(settings["rate"] * (end - start), rng)
    return {"a": [n], "b": [n]}


def experiment(model=split_counter):
    return Experiment(
        "split", "Split signal", "One measured count shared by two instruments.",
        (Parameter("rate", "Rate", "1/s", 120, 0, 1000),),
        (Device("a", "counter", "A"), Device("b", "counter", "B")), model,
    )


class SessionTests(unittest.TestCase):
    def test_seed_is_read_only_and_reproduces_the_random_stream(self):
        session = Session(experiment(), seed=187)
        self.assertEqual(session.seed, 187)
        with self.assertRaises(AttributeError):
            session.seed = 42
        with self.assertRaisesRegex(ValueError, "seed must be an integer"):
            Session(experiment(), seed=None)
        reference = Session(experiment(), seed=session.seed)
        for item in (session, reference):
            item.start(1.25)
            item.advance(1.25)
        self.assertEqual(session.records, reference.records)

    def test_unresolvable_gate_and_advance_do_not_create_zero_exposure(self):
        session = Session(experiment())
        session.start(1)
        session.advance(1)
        original = session.records.copy()
        with self.assertRaisesRegex(ValueError, "clock resolution"):
            session.start(1e-17)
        self.assertFalse(session.running)
        self.assertEqual(session.records, original)
        with self.assertRaisesRegex(ValueError, "clock resolution"):
            session.advance(1e-17)
        self.assertEqual(session.time_s, 1)
        session.start(0.25)
        session.advance(0.25)
        self.assertFalse(session.running)
        self.assertTrue(all(row.exposure_s > 0 for row in session.records))
        self.assertEqual(session.records[-1].exposure_s, 0.25)

    def test_small_resolvable_exposure_at_origin_remains_valid(self):
        session = Session(experiment())
        session.start(1e-17)
        session.advance(1e-17)
        self.assertFalse(session.running)
        self.assertEqual(session.records[0].exposure_s, 1e-17)

    def test_large_world_time_cannot_open_an_unresolvable_one_second_window(self):
        session = Session(experiment())
        session.advance(1e30)
        with self.assertRaisesRegex(ValueError, "clock resolution"):
            session.start()
        self.assertFalse(session.running)
        session.advance(0)
        self.assertEqual(session.time_s, 1e30)
        self.assertEqual(session.records, [])

    def test_timed_gate_stops_exposure_while_world_time_continues(self):
        reference = Session(experiment(), seed=442)
        reference.advance(5)
        reference.start(duration_s=2.25)
        reference.advance(10)
        self.assertEqual(reference.time_s, 15)
        self.assertFalse(reference.running)
        self.assertEqual([(r.start_s, r.end_s) for r in reference.records],
                         [(5, 6), (6, 7), (7, 7.25)])
        self.assertEqual(sum(r.exposure_s for r in reference.records), 2.25)
        other = Session(experiment(), seed=442)
        other.advance(5)
        other.start(2.25)
        for _ in range(100):
            other.advance(0.1)
        self.assertEqual(reference.records, other.records)
        other.start(0.25)
        other.advance(1)
        self.assertEqual(other.records[-1].exposure_s, 0.25)

    def test_gate_rejects_invalid_duration_without_opening(self):
        session = Session(experiment())
        for duration in (0, -1, float("nan"), float("inf"), True, "1"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                session.start(duration)
            self.assertFalse(session.running)
        session.start()
        session.start()
        with self.assertRaisesRegex(ValueError, "Stop the current gate"):
            session.start(1)

    def test_one_clock_independent_of_chunk_size(self):
        reference = Session(experiment(), seed=442)
        reference.start()
        reference.advance(3.7)
        reference.stop()
        other = Session(experiment(), seed=442)
        other.start()
        for _ in range(37):
            other.advance(0.1)
        other.stop()
        self.assertEqual(other.time_s, reference.time_s)
        self.assertEqual(other.records, reference.records)
        self.assertEqual(len(other.records), 4)
        for row in other.records:
            self.assertEqual(row.readings["a"], row.readings["b"])

    def test_condition_change_splits_window_and_stopping_closes_gate(self):
        session = Session(experiment())
        session.advance(2)
        session.start()
        session.advance(0.25)
        session.set("rate", 0)
        session.advance(0.75)
        session.stop()
        session.advance(1)
        self.assertEqual(session.time_s, 4)
        self.assertEqual(
            [(row.start_s, row.end_s, row.settings["rate"]) for row in session.records],
            [(2, 2.25, 120), (2.25, 3, 0)],
        )
        self.assertEqual(session.records[-1].readings["a"], (0,))

    def test_invalid_commands_do_not_sample_or_move_time(self):
        session = Session(experiment())
        session.start()
        session.advance(0.5)
        with self.assertRaises(ValueError):
            session.set("rate", float("nan"))
        with self.assertRaises(ValueError):
            session.advance(-1)
        self.assertEqual(session.time_s, 0.5)
        self.assertEqual(session.records, [])

    def test_bad_output_is_rejected_without_committing_measurement(self):
        session = Session(experiment(lambda *args: {"a": [1]}))
        session.start()
        with self.assertRaisesRegex(ValueError, "device ids"):
            session.advance(1)
        self.assertEqual(session.time_s, 0)
        self.assertEqual(session.records, [])

    def test_sessions_and_saved_settings_are_independent(self):
        definition = experiment()
        left, right = Session(definition, seed=42), Session(definition, seed=42)
        left.start()
        left.advance(1)
        saved = left.records[0]
        left.set("rate", 0)
        left.advance(1)
        self.assertEqual(saved.settings["rate"], 120)
        self.assertEqual(right.settings["rate"], 120)
        self.assertEqual(right.time_s, 0)
        self.assertEqual(right.records, [])
        right.start()
        right.advance(1)
        self.assertEqual(saved, right.records[0])
        with self.assertRaises(TypeError):
            saved.settings["rate"] = 3
        with self.assertRaises(TypeError):
            saved.readings["a"] = (3,)

    def test_failed_sample_can_retry_without_consuming_randomness(self):
        fail_once = [True]

        def transient(settings, start, end, rng):
            result = split_counter(settings, start, end, rng)
            if fail_once:
                fail_once.pop()
                return {"a": (-1,), "b": (0,)}
            return result

        session = Session(experiment(transient), seed=42)
        session.start(0.25)
        with self.assertRaisesRegex(ValueError, "nonnegative integer"):
            session.advance(1)
        self.assertEqual(session.time_s, 0)
        self.assertEqual(session.records, [])
        session.advance(1)
        reference = Session(experiment(), seed=42)
        reference.start(0.25)
        reference.advance(1)
        self.assertEqual(session.records, reference.records)


class CatalogTests(unittest.TestCase):
    def test_old_module_exposes_controls_and_distinct_counter_instances(self):
        entry = describe(experiment())
        parts = entry["components"]
        self.assertEqual([p["device"] for p in parts if p["device"]], ["a", "b"])
        self.assertEqual([key for p in parts for key in p["parameters"]], ["rate"])
        self.assertEqual(entry["connections"], [])

    def test_diagram_controls_and_detector_open_the_declared_model_and_device(self):
        for name, key, value, meter in (("alpha", "foil_um", 8, "mca"),
                                         ("beta", "foil_count", 4, "counter")):
            with self.subTest(experiment=name):
                definition = discover()[name]
                parts = {p["id"]: p for p in describe(definition)["components"]}
                session = Session(definition)
                session.set("foil_count", value)
                session.set_output(parts["detector"]["output"], True)
                session.start(1)
                session.advance(1)
                row = session.records[0]
                self.assertEqual(row.settings["foil_count"], value)
                self.assertIn(meter, row.readings)

    def test_invalid_diagram_points_to_the_bad_binding(self):
        base = discover()["alpha"]
        for part, reason in (
            (Component("gain", "knob", "Gain", parameters=("gain",)), "unknown parameter 'gain'"),
            (Component("adc", "instrument", "ADC", device="missing"), "unknown device 'missing'"),
        ):
            with self.subTest(part=part.id), self.assertRaisesRegex(ValueError, reason):
                replace(base, components=(*base.components, part))
        with self.assertRaisesRegex(ValueError, "broken"):
            replace(base, connections=(Connection("detector", "broken", "signal", "Pulse"),))

    def test_definition_rejects_invalid_parameter_and_device_bindings(self):
        def define(parameters, devices):
            return Experiment("invalid", "Invalid", "", parameters, devices, split_counter)

        parameter = Parameter("rate", "Rate", "1/s", 120, 0, 1000)
        counter = Device("a", "counter", "A")
        with self.assertRaisesRegex(ValueError, "duplicate parameter"):
            define((parameter, parameter), (counter,))
        with self.assertRaisesRegex(ValueError, "rate"):
            define((Parameter("rate", "Rate", "1/s", -1, 0, 1000),), (counter,))
        with self.assertRaisesRegex(ValueError, "distinct id"):
            define((), (counter, counter))
        with self.assertRaisesRegex(ValueError, "one channel"):
            define((), (Device("a", "counter", "A", channels=2),))

    def test_builtins_share_discovery_and_chunk_invariant_acquisition(self):
        definitions = discover()
        self.assertTrue({"alpha", "beta"} <= definitions.keys())
        for name in ("alpha", "beta"):
            with self.subTest(experiment=name):
                left = Session(definitions[name], seed=2026)
                right = Session(definitions[name], seed=2026)
                for session in (left, right):
                    for output in session.experiment.outputs:
                        session.set_output(output.id, True)
                    session.start(1.25)
                left.advance(2)
                for _ in range(20):
                    right.advance(0.1)
                self.assertEqual(left.records, right.records)
                device = left.experiment.devices[0].id
                self.assertEqual(sum(r.exposure_s for r in left.records if device in r.readings), 1.25)

    def test_invalid_module_reports_its_origin(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.py"
            path.write_text("EXPERIMENT = None", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid.py.*Experiment"):
                discover([directory])

    def test_discover_external_module_and_reject_duplicate_id(self):
        src = (
            "from nuclemu.core import Experiment, Device\n"
            "def read(settings, start, end, rng): return {'m': [7]}\n"
            "EXPERIMENT = Experiment('example-test', 'Lab', '', (), "
            "(Device('m', 'counter', 'M'),), read)\n"
        )
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "example.py").write_text(src, encoding="utf-8")
            definition = discover([path])["example-test"]
            session = Session(definition)
            session.start()
            session.advance(1)
            self.assertEqual(session.records[0].readings["m"], (7,))
            (path / "duplicate.py").write_text(src, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate experiment"):
                discover([path])


class PhysicsTests(unittest.TestCase):
    def test_foil_unit_conversion_and_invalid_thickness(self):
        self.assertAlmostEqual(AluminumFoil(0.1).areal_density_g_cm2, 0.027)
        self.assertEqual(AluminumFoil(0).areal_density_g_cm2, 0)
        for thickness in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                AluminumFoil(thickness)

    def test_poisson_moments_across_sampler_branches(self):
        for expected in (0.1, 5, 29, 30, 120, 10000):
            with self.subTest(mean=expected):
                rng = Random(42)
                values = [poisson(expected, rng) for _ in range(12000)]
                self.assertAlmostEqual(mean(values), expected,
                                       delta=6 * (expected / len(values)) ** 0.5)
                self.assertAlmostEqual(variance(values), expected,
                                       delta=0.1 * expected)
        self.assertEqual(poisson(0, Random(42)), 0)
        for expected in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                poisson(expected, Random(42))


if __name__ == "__main__":
    unittest.main()
