"""Single instruments expose the same executable actions as grouped members."""

from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest

from nuclemu.experiments.alpha import EXPERIMENT
from nuclemu.web_session import Application


class SingleInstrumentActionTests(unittest.TestCase):
    def test_legacy_course_without_named_outputs_keeps_its_shared_gate(self):
        from tests.legacy_web_fixture import legacy_course
        definition = legacy_course('alpha')
        with TemporaryDirectory() as folder:
            now = [0]
            app = Application({definition.id: definition}, folder, clock=lambda: now[0])
            state = app.open({'experiment': definition.id})
            self.assertEqual(state['instrument_groups'], {})
            state = app.request('/api/action', dict(session=app.lab.id, action='start', duration=1))
            self.assertTrue(state['running'])
            now[0] = 1
            state = app.state()
            self.assertFalse(state['running'])
            self.assertEqual(state['instrument_groups'], {})

    def test_timed_limit_and_target_extension_keep_single_instrument_actions_truthful(self):
        for definition in (EXPERIMENT, replace(EXPERIMENT, components=(), connections=())):
            with self.subTest(inferred=not definition.components), TemporaryDirectory() as folder:
                now = [0]
                app = Application({definition.id: definition}, folder, clock=lambda: now[0])
                state = app.open({'experiment': definition.id})
                component = next(p['id'] for p in state['definition']['components'] if p.get('device') == 'mca')
                def act(action, **fields):
                    return app.request('/api/action', dict(session=app.lab.id, action=action, **fields))
                self.assertEqual(state['instrument_groups'][component], dict(can_start=True, can_stop=False))
                act('instrument_config', device='mca', duration_s=1)
                state = act('start', device='mca')
                self.assertEqual(state['instrument_groups'][component], dict(can_start=False, can_stop=True))
                now[0] = 1
                state = app.state()
                acquisition = state['instrument']['acquisition']
                self.assertEqual(state['instrument_groups'][component], dict(can_start=False, can_stop=False))
                self.assertEqual(state['instrument']['exposure_s'], 1)
                saved = app.lab.work.session.snapshot('mca')
                state = act('instrument_config', device='mca', duration_s=2)
                self.assertTrue(state['instrument_groups'][component]['can_start'])
                act('start', device='mca')
                now[0] = 2
                state = app.state()
                self.assertEqual(state['instrument']['acquisition'], acquisition)
                self.assertEqual(state['instrument']['exposure_s'], 2)
                self.assertEqual(saved.exposure_s, 1)
                self.assertFalse(state['instrument_groups'][component]['can_start'])
                state = act('instrument_config', device='mca', duration_s=None)
                self.assertTrue(state['instrument_groups'][component]['can_start'])


if __name__ == '__main__':
    unittest.main()
