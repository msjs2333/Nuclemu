"""Optional teaching metadata must not change numeric measurements or old modules."""

from dataclasses import replace
import json
import unittest

from nuclemu.catalog import describe, discover, resolve_short_code
from nuclemu.core import Device, Experiment, Parameter, Session


def counter(settings, start, end, rng):
    return {"meter": (int(settings["mode"] * (end - start)),)}


def definition():
    return Experiment("custom", "Counter", "Example", (
        Parameter("mode", "Mode", "", 2, 0, 2, integer=True,
                  options=((0, "Sample"), (2, "Background"))),
    ), (Device("meter", "counter", "Meter", background_conditions={"mode": 2}),), counter,
        course="Counting course")


class OptionalMetadataTests(unittest.TestCase):
    def test_short_codes_are_public_metadata_with_safe_legacy_defaults(self):
        for name, code in (("alpha", "AEL"), ("beta", "BABS")):
            exp = discover()[name]
            self.assertEqual(exp.short_code, code)
            self.assertEqual(describe(exp)["short_code"], code)
        old = definition()
        self.assertEqual(old.short_code, "custom")
        self.assertEqual(resolve_short_code("clock-pulses"), "clock-pulses")
        for identifier in ("../course name\\example", "α能损", "x" * 100):
            code = resolve_short_code(identifier)
            self.assertRegex(code, r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
            self.assertEqual(code, resolve_short_code(identifier))
        for value in ("", "a/b", "a\\b", "..", " space", "中文", "x" * 33, 123):
            with self.subTest(short_code=value), self.assertRaisesRegex(ValueError, "short_code"):
                replace(old, short_code=value)
        custom = replace(old, short_code="TEACH_1")
        session = Session(custom)
        session.start(1)
        session.advance(1)
        self.assertEqual(session.records[0].readings["meter"], (2,))

    def test_custom_parameter_and_nonzero_background_serialize_without_beta_assumptions(self):
        exp = definition()
        info = json.loads(json.dumps(describe(exp)))
        self.assertEqual(info["course"], "Counting course")
        self.assertEqual(info["parameters"][0]["options"],
                         [{"value": 0, "label": "Sample"}, {"value": 2, "label": "Background"}])
        self.assertEqual(info["devices"][0]["background_conditions"], {"mode": 2})
        # A saved definition can recreate numeric constraints using its own metadata.
        restored = replace(exp, parameters=tuple(Parameter(**p) for p in info["parameters"]),
                           devices=tuple(Device(**d) for d in info["devices"]))
        session = Session(restored, seed=42)
        session.start(1)
        session.advance(1)
        session.set("mode", 0.0)
        session.start(1)
        session.advance(1)
        self.assertEqual([r.readings["meter"][0] for r in session.records], [2, 0])
        self.assertIs(type(session.settings["mode"]), int)
        with self.assertRaisesRegex(ValueError, "options"):
            session.set("mode", 1)

    def test_legacy_definition_and_archived_fields_use_defaults(self):
        old = Experiment("old", "Old", "", (Parameter("mode", "Mode", "", 1, 0, 2),),
                         (Device("meter", "counter", "Meter"),), counter)
        entry = describe(old)
        self.assertEqual(entry["course"], "核物理实验")
        self.assertEqual(entry["parameters"][0]["options"], [])
        self.assertEqual(entry["devices"][0]["background_conditions"], {})
        # Historic archives omit all three new fields.
        parameter = dict(entry["parameters"][0]); parameter.pop("options")
        device = dict(entry["devices"][0]); device.pop("background_conditions")
        restored = Experiment("old", "Old", "", (Parameter(**parameter),),
                              (Device(**device),), counter)
        self.assertEqual(restored, old)
        self.assertEqual(restored.parameters[0].value(0.5), 0.5)

    def test_option_constraints_fail_at_definition_or_setting_boundary(self):
        exp = definition()
        for options in (((0, "A"), (0.0, "B")), ((3, "Out of range"),),
                        ((1.5, "Fraction"),), ((2, ""),), ((True, "Boolean"),), ((2,),)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                replace(exp, parameters=(replace(exp.parameters[0], options=options),))
        with self.assertRaisesRegex(ValueError, "options"):
            replace(exp, parameters=(replace(exp.parameters[0], default=1),))

    def test_background_binding_and_course_are_checked_at_definition_boundary(self):
        exp = definition()
        for conditions in ({"unknown": 0}, {"mode": 1}, (("mode", 2), ("mode", 2))):
            with self.subTest(conditions=conditions), self.assertRaises(ValueError):
                replace(exp, devices=(replace(exp.devices[0], background_conditions=conditions),))
        with self.assertRaisesRegex(ValueError, "counter"):
            replace(exp, devices=(replace(exp.devices[0], kind="spectrum"),))
        with self.assertRaisesRegex(ValueError, "course"):
            replace(exp, course=" ")

    def test_beta_declares_background_independently_of_option_labels(self):
        beta = discover()["beta"]
        self.assertEqual(dict(beta.devices[0].background_conditions), {"source_present": 0})
        self.assertEqual({value for value, _ in beta.parameters[0].options}, {0, 1})
        self.assertTrue(all(label for _, label in beta.parameters[0].options))
        self.assertEqual(discover()["alpha"].devices[0].background_conditions, ())


if __name__ == "__main__":
    unittest.main()
