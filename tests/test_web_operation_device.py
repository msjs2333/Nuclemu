"""File actions target a window without changing the displayed instrument."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Component, Device, Experiment, SignalOutput
from nuclemu.exchange import load_package, reopen_session
from nuclemu.web_session import Application


def course():
    return Experiment('boxes', 'Boxes', '', (),
        tuple(Device(d, 'counter', d, input='detector') for d in ('a', 'b', 'c')),
        lambda settings, start, end, rng: {'detector': (round(10 * (end - start)),)},
        outputs=(SignalOutput('detector', 'Detector'),),
        components=(Component('detector', 'detector', 'Detector', output='detector'),
                    Component('pair', 'instrument', 'Pair', device='a', devices=('a', 'b')),
                    Component('solo', 'instrument', 'Solo', device='c')))


class OperationDeviceTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 0
        self.definition = course()
        self.app = Application({self.definition.id: self.definition}, folder.name, lambda: self.now)
        self.app.open({'experiment': self.definition.id})
        self.call('output', output='detector', enabled=True)
        self.call('start_group', component='pair')
        self.now = 3
        self.app.state()

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def unchanged(self):
        lab, session = self.app.lab, self.app.lab.work.session
        return (lab.work.device.id, lab.work.lab.selected, session.time_s, session._rng.getstate(),
                tuple(session.instrument(d.id) for d in self.definition.devices), session.snapshots,
                tuple(session.records), deepcopy(lab.analysis), lab.edits)

    def test_snapshot_b_does_not_change_page_selection_or_any_gate(self):
        lab = self.app.lab
        before = tuple(lab.work.session.instrument(d.id) for d in self.definition.devices)
        selection = deepcopy(lab.analysis)
        state = self.call('snapshot', device='a', operation_device='b')
        self.assertEqual(state['device'], 'a')
        self.assertEqual(lab.work.device.id, 'a')
        self.assertEqual(lab.analysis, selection)
        self.assertEqual(tuple(lab.work.session.instrument(d.id) for d in self.definition.devices), before)
        saved = lab.work.session.snapshots[0]
        self.assertEqual((saved.device, saved.counts, saved.exposure_s), ('b', (30,), 3))
        document = load_package(lab.portable_download()[2])
        reopened = reopen_session(document, self.definition)
        self.assertEqual(reopened.snapshots[0], saved)

    def test_clear_confirmation_and_all_choices_keep_the_same_target_and_page(self):
        for choice in ('save', 'discard', 'cancel'):
            with self.subTest(choice=choice):
                self.setUp()
                request = self.call('begin_clear', device='a', operation_device='b')['clear_confirmation']
                self.assertEqual((request['device'], request['exposure_s']), ('b', 3))
                self.now = 5
                # Reconnected state retains the actual B confirmation, not the page's A context.
                state = self.app.state()
                self.assertEqual(state['device'], 'a')
                self.assertEqual(state['clear_confirmation']['token'], request['token'])
                self.call('finish_clear', device='a', operation_device='b', token=request['token'], choice=choice)
                self.now = 6
                state = self.app.state()
                session = self.app.lab.work.session
                self.assertEqual(state['device'], 'a')
                self.assertIsNone(state['clear_confirmation'])
                self.assertEqual((session.instrument('a').counts, session.instrument('a').exposure_s), ((60,), 6))
                self.assertEqual((session.instrument('b').counts, session.instrument('b').exposure_s),
                                 ((40,), 4) if choice == 'cancel' else ((0,), 0))
                self.assertEqual(len(session.snapshots), 1 if choice == 'save' else 0)
                if choice == 'save':
                    self.assertEqual((session.snapshots[0].device, session.snapshots[0].counts), ('b', (30,)))
                with self.assertRaises(ValueError):
                    self.call('finish_clear', device='a', operation_device='b', token=request['token'], choice=choice)

    def test_stale_context_cross_box_and_unknown_targets_are_rejected_before_sampling(self):
        for action in ('snapshot', 'begin_clear'):
            for fields in (dict(device='b', operation_device='b'), dict(device='a', operation_device='c'),
                           dict(device='a', operation_device='missing'), dict(device='a', operation_device=None),
                           dict(operation_device='b'), dict(device='b')):
                with self.subTest(action=action, fields=fields):
                    before = self.unchanged()
                    self.now = 4
                    with self.assertRaises(ValueError):
                        self.call(action, **fields)
                    self.assertEqual(self.unchanged(), before)
                    self.now = 3

    def test_stale_clear_choice_keeps_pending_target_until_page_context_is_valid(self):
        request = self.call('begin_clear', device='a', operation_device='b')['clear_confirmation']
        self.call('device', device='c')
        before = self.unchanged()
        for context in ('a', 'c'):
            with self.assertRaises(ValueError):
                self.call('finish_clear', device=context, operation_device='b', token=request['token'], choice='discard')
            self.assertEqual(self.unchanged(), before)
        self.assertTrue(self.app.lab.work.session.instrument('b').clearing)
        self.call('device', device='a')
        self.call('finish_clear', device='a', operation_device='b', token=request['token'], choice='cancel')
        self.assertFalse(self.app.lab.work.session.instrument('b').clearing)
        self.assertEqual(self.app.lab.work.device.id, 'a')


if __name__ == '__main__':
    unittest.main()
