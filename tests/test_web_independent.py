"""The selected Web instrument owns its gate, exposure and sparse measurements."""

from copy import deepcopy
from base64 import b64encode
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.core import Device, Experiment
from nuclemu.exchange import load_package
from nuclemu.web_session import Application


class IndependentWebTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.app = Application(discover(['examples/courses']), self.folder.name, lambda: self.now)
        self.app.open({'experiment': 'split-signal', 'seed': 187})

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def test_student_apparatus_state_only_exposes_foil_dimensions(self):
        for course in ('alpha', 'beta'):
            with self.subTest(course=course):
                app = Application(discover(), self.folder.name, lambda: 0)
                app.open({'experiment': course})
                state = app.request('/api/action', dict(session=app.lab.id, action='configure',
                                    values={'foil_count': 2, 'source_present': 1}))
                model = app.lab.work.session.particle_flow
                self.assertIn('transmitted_rate_s', model)
                self.assertEqual(state['particle_flow'], {
                    key: model[key] for key in ('thickness_um', 'areal_density_g_cm2')})

    def test_idle_b_can_open_and_stop_without_closing_a(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a', duration=10)
        self.now = 1.25
        state = self.call('device', device='b')
        self.assertFalse(state['running'])
        self.assertTrue(state['any_running'])
        self.assertEqual(state['exposure_s'], 0)
        self.assertIsNone(state['remaining_s'])
        self.assertIsNone(state['readout'])
        self.assertEqual({m['device'] for m in state['unsaved']['measurements']}, {'a'})
        state = self.call('start', device='b', duration=2)
        self.now = 1.75
        state = self.app.state()
        self.assertEqual(state['exposure_s'], .5)
        self.assertEqual(state['remaining_s'], 1.5)
        # The partial statistical window has no completed observation yet.
        self.assertIsNone(state['readout'])
        self.call('stop', device='b', acquisition=state['active_acquisition'], cycle=state['instrument']['cycle'])
        state = self.call('device', device='a')
        self.assertTrue(state['running'])
        self.assertEqual(state['remaining_s'], 8.25)
        state = self.call('device', device='b')
        self.assertEqual(state['readout']['exposure_s'], .5)
        self.assertFalse(state['running'])

    def test_multiple_device_tails_reach_delta_draft_and_unsaved_lists(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a', duration=10)
        self.call('device', device='b')
        self.call('start', device='b', duration=10)
        self.now = 1
        first = deepcopy(self.app.state())
        self.call('snapshot', device='b')
        self.call('device', device='a')
        self.call('snapshot', device='a')
        self.call('device', device='b')
        self.now = 2
        second = self.app.state(product_cursor=first['product_cursor'])
        self.assertEqual(second['product_delta']['start'], 0)
        self.assertEqual([s['end_s'] for s in second['product_delta']['segments']], [2, 2])
        self.assertEqual({m['device'] for m in second['unsaved']['measurements']}, {'a', 'b'})
        self.now = 3
        self.app.state()
        delayed = self.app.state(product_cursor=first['product_cursor'])
        self.assertEqual(delayed['product_delta']['start'], 0)
        self.assertEqual(self.app.catalog()['drafts'], [])
        state = self.app.state()
        self.call('stop', device='b', acquisition=state['active_acquisition'], cycle=state['instrument']['cycle'])
        self.now = 4
        final = self.app.state()
        self.assertEqual(final['measurement_end_s'], 4)
        doc = load_package(self.app.lab.portable_download()[2])
        self.assertEqual([i['document']['snapshot']['exposure_s'] for i in doc['items']], [1, 1])
        self.assertEqual([s['end_s'] for s in final['product']['segments']], [4, 3])

    def test_another_instruments_segment_is_not_a_selection_or_background(self):
        self.call('start', device='a', duration=1)
        self.now = 1
        self.app.state()
        self.call('device', device='b')
        for action, fields in [('select', {'index': 0}), ('analysis', {'background': 0})]:
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, '不属于当前仪器'):
                self.call(action, device='b', **fields)
        # Export may explicitly address a device other than the displayed one.
        exported = self.app.lab.export(dict(device='a', format='csv', indices=[0]))
        self.assertIn(b'count', exported)

    def test_stale_stop_cannot_pause_a_resumed_cycle_of_the_same_round(self):
        first = self.call('start', device='a', duration=10)
        self.now = .25
        self.call('stop', device='a', acquisition=first['active_acquisition'], cycle=first['instrument']['cycle'])
        resumed = self.call('start', device='a', duration=10)
        self.assertEqual(first['active_acquisition'], resumed['active_acquisition'])
        self.assertNotEqual(first['instrument']['cycle'], resumed['instrument']['cycle'])
        self.now += .5
        with self.assertRaisesRegex(ValueError, '采集门已改变'):
            self.call('stop', device='a', acquisition=first['active_acquisition'], cycle=first['instrument']['cycle'])
        self.assertEqual(self.app.lab.work.session.time_s, .25)
        self.assertTrue(self.app.lab.work.session.instrument('a').running)

    def test_running_save_keeps_elapsed_time_during_disk_write(self):
        self.call('start', device='a', duration=10)
        self.now = 1
        self.app.state()
        def slow_write(item):
            self.now += 2
        self.app.lab.cache_writer = slow_write
        self.call('snapshot', device='a')
        state = self.app.state()
        self.assertTrue(state['running'])
        self.assertEqual(state['exposure_s'], 3)
        self.assertEqual(state['instrument']['readable_exposure_s'], 3)

    def test_legacy_course_keeps_shared_gate_and_completed_readout(self):
        definition = Experiment('legacy', 'Shared gate', '', (),
            (Device('x', 'counter', 'X'), Device('y', 'counter', 'Y')),
            lambda settings, start, end, rng: {'x': (2,), 'y': (4,)})
        self.app = Application({'legacy': definition}, self.folder.name, lambda: self.now)
        self.app.open({'experiment': 'legacy'})
        self.call('start', duration=2)
        self.now = 1.5
        state = self.call('device', device='y')
        self.assertTrue(state['running'])
        self.assertIsNone(state['instrument'])
        self.assertEqual(state['readout']['counts'], 4)
        self.assertEqual(state['readout']['exposure_s'], 1)
        state = self.call('stop', acquisition=state['active_acquisition'])
        self.assertFalse(state['running'])
        self.assertEqual(state['readout']['exposure_s'], 1.5)

    def test_detector_only_clock_and_running_save_do_not_create_partial_readings(self):
        self.call('output', output='detector', enabled=True)
        self.now = .5
        state = self.app.state()
        self.assertEqual(state['time_s'], .5)
        self.assertTrue(state['clock_running'])
        self.assertFalse(state['any_running'])
        self.call('start', device='a', duration=10)
        self.now = 1.75
        state = deepcopy(self.app.state())
        session = self.app.lab.work.session
        rng = session._rng.getstate()
        count = len(session.records)
        self.call('snapshot', device='a')
        self.assertTrue(session.instrument('a').running)
        self.assertEqual(len(session.records), count)
        self.assertEqual(session._rng.getstate(), rng)
        payload = self.app.lab.portable_download()[2]
        doc = load_package(payload)
        self.assertEqual(doc['items'][0]['document']['segments'], state['product']['segments'])
        self.assertLess(state['readout']['exposure_s'], state['exposure_s'])
        # The existing archive remains readable without regenerating observations.
        token = self.call('freeze')['confirmation_id']
        self.call('discard', confirmation_id=token)
        self.assertEqual(self.app.catalog()['archives'], [])
        reopened = self.app.request('/api/open_package', {'file': b64encode(payload).decode()})
        self.assertFalse(reopened['readonly'])
        self.assertEqual(reopened['snapshots'][0]['exposure_s'], doc['items'][0]['document']['snapshot']['exposure_s'])


if __name__ == '__main__':
    unittest.main()
