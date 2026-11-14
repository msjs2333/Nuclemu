"""Group action availability uses the same preflight as actual acquisition."""
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Component, Device, Session
from nuclemu.catalog import describe
from nuclemu.experiments.beta import EXPERIMENT as CURRENT, LEGACY_INDEPENDENT_RESPONSES, restore_definition
from nuclemu.web_session import Application

GROUP = ('counter', 'counter_b')
# The 97/105 boundary is a historical-response regression, not the current
# course's much higher-rate response. Restore its explicit saved contract.
_info = describe(CURRENT)
for _output, _response in zip(_info['outputs'], LEGACY_INDEPENDENT_RESPONSES):
    _output['response'] = _response
EXPERIMENT = restore_definition(_info)


def beta():
    s = Session(EXPERIMENT, seed=187)
    s.set('source_present', 1)
    s.set_output('beta_detector', True)
    return s


class GroupStateTests(unittest.TestCase):
    def unchanged(self, s):
        return (s.time_s, tuple(s.instrument(d.id) for d in s.experiment.devices),
                tuple(s.records), s._rng.getstate(), tuple(s.rounds), tuple(s.snapshots))

    def test_mixed_count_limit_retains_pause_and_requires_a_sufficient_new_target(self):
        s = beta()
        s.configure_group(GROUP, count_limit=100)
        self.assertEqual(s.group_state(GROUP), dict(can_start=True, can_stop=False))
        s.start_group(GROUP)
        s.advance(1)
        self.assertEqual([s.instrument(d).counts for d in GROUP], [(97,), (105,)])
        self.assertEqual([s.instrument(d).running for d in GROUP], [True, False])
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=True))
        before = self.unchanged(s)
        for _ in range(5):
            self.assertFalse(s.group_state(GROUP)['can_start'])
        with self.assertRaisesRegex(ValueError, 'limit reached'):
            s.start_group(GROUP)
        with self.assertRaisesRegex(ValueError, 'Pause'):
            s.configure_group(GROUP, count_limit=200)
        self.assertEqual(self.unchanged(s), before)
        saved = s.snapshot('counter_b')
        s.stop_group(GROUP)
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=False))
        s.configure_group(GROUP, count_limit=105)
        self.assertFalse(s.group_state(GROUP)['can_start'])
        s.configure_group(GROUP, count_limit=200)
        self.assertTrue(s.group_state(GROUP)['can_start'])
        s.start_group(GROUP)
        s.advance(1)
        self.assertEqual([s.instrument(d).counts for d in GROUP], [(191,), (196,)])
        self.assertEqual([s.instrument(d).acquisition for d in GROUP], [1, 1])
        self.assertEqual(saved.counts, (105,))

    def test_partial_exposure_polling_does_not_settle_or_consume_randomness(self):
        s = beta()
        s.start_group(GROUP)
        s.advance(.25)
        before = self.unchanged(s)
        for _ in range(10):
            self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=True))
        self.assertEqual(self.unchanged(s), before)

    def test_timed_mixed_state_uses_each_gate_actual_exposure(self):
        s = beta()
        s.configure_acquisition('counter', duration_s=1)
        s.configure_acquisition('counter_b', duration_s=2)
        s.start_group(GROUP)
        s.advance(1)
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=True))
        s.stop_group(GROUP)
        s.configure_group(GROUP, duration_s=3)
        self.assertEqual(s.group_state(GROUP), dict(can_start=True, can_stop=False))
        s.start_group(GROUP)
        s.advance(2)
        self.assertEqual([s.instrument(d).exposure_s for d in GROUP], [3, 3])
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=False))

    def test_pending_clear_blocks_only_its_group_and_group_validation_remains_strict(self):
        course = replace(EXPERIMENT, devices=(*EXPERIMENT.devices,
            Device('solo', 'counter', 'Solo', input='beta_detector')),
            components=(*EXPERIMENT.components, Component('solo', 'instrument', 'Solo', device='solo')))
        s = Session(course)
        s.start_group((*GROUP, 'solo'))
        s.advance(1)
        clear_solo = s.begin_clear('solo')
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=True))
        s.finish_clear('solo', clear_solo.token, 'cancel')
        request = s.begin_clear('counter')
        self.assertEqual(s.group_state(GROUP), dict(can_start=False, can_stop=False))
        with self.assertRaisesRegex(ValueError, 'clear request'):
            s.start_group(GROUP)
        s.finish_clear('counter', request.token, 'cancel')
        for group in ((), ('counter', 'counter'), ('unknown',), 'counter'):
            with self.subTest(group=group), self.assertRaises(ValueError):
                s.group_state(group)


class WebGroupStateTests(unittest.TestCase):
    def test_web_group_actions_match_real_requests_and_update_after_explicit_target_change(self):
        with TemporaryDirectory() as folder:
            now = [0]
            app = Application({'beta': EXPERIMENT}, folder, clock=lambda: now[0])
            app.open({'experiment': 'beta', 'seed': 187})
            def act(action, **fields):
                if action == 'stop_group':
                    fields['gate_cycles'] = {d: app.lab.work.session.instrument(d).cycle for d in GROUP}
                return app.request('/api/action', dict(session=app.lab.id, action=action, **fields))
            act('configure', values={'source_present': 1})
            act('output', output='beta_detector', enabled=True)
            state = act('instrument_group_config', component='counter', count_limit=100)
            self.assertEqual(state['instrument_groups']['counter'], dict(can_start=True, can_stop=False))
            act('start_group', component='counter')
            now[0] = 1
            state = app.state()
            self.assertEqual(state['instrument_groups']['counter'], dict(can_start=False, can_stop=True))
            self.assertEqual(state['instruments']['counter_b']['stop_reason'], 'count_limit')
            with self.assertRaisesRegex(ValueError, 'limit reached'):
                act('start_group', component='counter')
            state = act('stop_group', component='counter')
            self.assertEqual(state['instrument_groups']['counter'], dict(can_start=False, can_stop=False))
            state = act('instrument_group_config', component='counter', count_limit=200)
            self.assertTrue(state['instrument_groups']['counter']['can_start'])
            state = act('start_group', component='counter')
            self.assertTrue(state['instrument_groups']['counter']['can_stop'])
            now[0] = 2
            state = app.state()
            self.assertEqual([state['instruments'][d]['counts'] for d in GROUP], [(191,), (196,)])


if __name__ == '__main__':
    unittest.main()
