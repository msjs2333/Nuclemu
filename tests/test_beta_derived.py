"""Registered beta-derived courses keep their own model during file reopen."""

from base64 import b64encode
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover, resolve_saved_experiment, describe
from nuclemu.core import Session
from nuclemu.exchange import capture_session, save_package, package_bytes
from nuclemu.experiments import beta
from nuclemu.web_session import Application


class DerivedBetaTests(unittest.TestCase):
    def open_and_measure(self, course, folder):
        session = Session(course, seed=187)
        devices = ('counter', 'counter_b')
        session.set_output('beta_detector', True)
        session.start_group(devices)
        session.advance(2)
        session.stop_group(devices)
        for device in devices:
            session.snapshot(device)
        path = Path(folder) / 'class-b.nuclemu'
        save_package(path, capture_session(session))
        app = Application({course.id: course}, folder, clock=lambda: 0)
        state = app.request('/api/open_package', {'file': b64encode(path.read_bytes()).decode('ascii')})
        self.assertEqual(state['definition']['id'], course.id)
        self.assertEqual(state['definition']['title'], course.title)
        live = app.lab.work.session
        self.assertIs(live.experiment, course)
        self.assertEqual([s.counts for s in live.snapshots], [(46,), (92,)])
        live.set_output('beta_detector', True)
        live.start_group(devices)
        live.advance(1)
        self.assertEqual([live.snapshot(d).counts for d in devices], [(23,), (46,)])

    def test_registered_module_with_inherited_callback_preserves_custom_course(self):
        with TemporaryDirectory() as folder:
            Path(folder, 'class_b.py').write_text(
                "from dataclasses import replace\n"
                "from nuclemu.experiments import beta\n"
                "def pulses(settings, start, end, rng):\n"
                "    return {o.id: (round((i+1)*23*(end-start)),) for i,o in enumerate(beta.EXPERIMENT.outputs)}\n"
                "EXPERIMENT = replace(beta.EXPERIMENT, id='beta-class-b', title='Class B', model=pulses,\n"
                "    outputs=tuple(replace(o,response='Class B response '+o.id) for o in beta.EXPERIMENT.outputs))\n",
                encoding='utf-8')
            course = discover([folder])['beta-class-b']
            self.open_and_measure(course, folder)

    def test_same_id_teacher_variant_preserves_its_title_response_and_model(self):
        def pulses(settings, start, end, rng):
            return {o.id: (round((i+1)*23*(end-start)),) for i, o in enumerate(beta.EXPERIMENT.outputs)}
        course = replace(beta.EXPERIMENT, title='Class B', model=pulses,
                         outputs=tuple(replace(o, response='Class B response') for o in beta.EXPERIMENT.outputs))
        with TemporaryDirectory() as folder:
            self.open_and_measure(course, folder)

    def test_explicit_teacher_callback_is_called_and_wrong_id_is_still_rejected(self):
        calls = []
        def restore(saved):
            calls.append(saved['id'])
            return course
        course = replace(beta.EXPERIMENT, id='beta-class-b', restore_definition=restore)
        self.assertIs(resolve_saved_experiment(course, describe(course)), course)
        self.assertEqual(calls, ['beta-class-b'])
        with self.assertRaisesRegex(ValueError, 'different experiment'):
            resolve_saved_experiment(course, describe(beta.EXPERIMENT))
        self.assertEqual(calls, ['beta-class-b'])
        bad = replace(course, restore_definition=lambda saved: beta.EXPERIMENT)
        with self.assertRaisesRegex(ValueError, 'same id'):
            resolve_saved_experiment(bad, describe(course))

    def test_derived_course_still_rejects_a_changed_saved_input_binding(self):
        course = replace(beta.EXPERIMENT, id='beta-class-b')
        document = capture_session(Session(course))
        document['definition']['devices'][1]['input'] = 'unknown-input'
        with TemporaryDirectory() as folder:
            app = Application({course.id: course}, folder, clock=lambda: 0)
            with self.assertRaises(ValueError):
                app.request('/api/open_package', {'file': b64encode(package_bytes(document)).decode('ascii')})


if __name__ == '__main__':
    unittest.main()
