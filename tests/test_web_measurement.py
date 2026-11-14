"""A load confirmation authorizes replacement of one instrument round."""

from base64 import b64encode
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.exchange import capture_session, export_item, load_package
from nuclemu.web_session import Application


class MeasurementConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.definition = Experiment('load-test', 'Load test', '',
            (Parameter('rate', 'Rate', '1/s', 10, 0, 100),),
            (Device('a', 'counter', 'A', input='detector'),
             Device('b', 'counter', 'B', input='detector')),
            lambda settings, start, end, rng: {'detector': (int(settings['rate'] * (end - start)),)},
            outputs=(SignalOutput('detector', 'Detector'),))
        self.app = Application({self.definition.id: self.definition}, self.folder.name, lambda: self.now)
        self.app.open({'experiment': self.definition.id, 'seed': 187})
        self.session = self.app.lab.work.session
        source = Session(self.definition)
        source.start(2, device='a')
        source.advance(2)
        source.snapshot('a')
        document = capture_session(source)
        self.raw = export_item(document, document['items'][0]['id'])

    def call(self, action, **fields):
        if action == 'stop':
            target = self.session.instrument(fields['device'])
            fields.update(cycle=target.cycle, acquisition=target.acquisition)
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def inspect(self):
        return self.app.request('/api/inspect_measurement', dict(session=self.app.lab.id,
            device='a', file=b64encode(self.raw).decode()))

    def load(self, pending, **fields):
        return self.call('load_measurement', token=pending['token'],
                         item_id=pending['items'][0]['id'], **fields)

    def current(self):
        lab = self.app.lab
        return (self.session.instrument('a'), self.session.instrument('b'),
                self.session._rng.getstate(), self.session.records, self.session.snapshots,
                deepcopy(lab.analysis), dict(lab.work.lab.calibrations),
                dict(lab._live_calibrations), set(lab._saved_calibration_devices), lab.edits)

    def clear(self):
        request = self.call('begin_clear', device='a')['clear_confirmation']
        self.call('finish_clear', device='a', token=request['token'], choice='discard')

    def test_old_confirmation_cannot_replace_a_new_round_or_cleared_instrument(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a', duration=2)
        self.call('device', device='b')
        self.call('start', device='b')
        self.call('device', device='a')
        self.now = 2
        pending = self.inspect()
        self.assertTrue(pending['overwrite_required'])
        self.clear()
        before = self.current()
        with self.assertRaisesRegex(ValueError, '轮次.*改变'):
            self.load(pending, overwrite=True)
        self.assertEqual(self.current(), before)
        self.call('start', device='a', duration=4)
        self.now = 6
        self.app.state()
        self.assertEqual((self.session.instrument('a').counts,
                          self.session.instrument('a').exposure_s), ((40,), 4))
        before = self.current()
        with self.assertRaisesRegex(ValueError, '轮次.*改变'):
            self.load(pending, overwrite=True)
        self.assertEqual(self.current(), before)
        self.call('snapshot', device='a')
        saved = load_package(self.app.lab.portable_download()[2])
        product = saved['items'][0]['document']
        self.assertEqual((sum(row['readings']['a'][0] for row in product['segments']),
                          product['snapshot']['exposure_s']), (40, 4))
        fresh = self.inspect()
        self.load(fresh, overwrite=True)
        self.assertEqual((self.session.instrument('a').counts,
                          self.session.instrument('a').exposure_s), ((0,), 2))
        self.assertEqual(self.session.instrument('b').counts, (60,))

    def test_same_round_continuation_and_conditions_keep_confirmation_valid(self):
        self.call('output', output='detector', enabled=True)
        self.call('start', device='a')
        self.now = 2
        pending = self.inspect()
        acquisition = self.session.instrument('a').acquisition
        self.call('stop', device='a')
        self.call('configure', values={'rate': 20})
        self.call('start', device='a')
        self.now = 3
        self.call('stop', device='a')
        self.assertEqual(self.session.instrument('a').acquisition, acquisition)
        self.assertEqual(self.session.instrument('a').counts, (40,))
        self.load(pending, overwrite=True)
        self.assertEqual(self.session.instrument('a').counts, (0,))
        self.assertEqual(self.session.settings['rate'], 20)
        with self.assertRaisesRegex(ValueError, '过期'):
            self.load(pending, overwrite=True)

    def test_empty_target_confirmation_cannot_replace_started_round(self):
        pending = self.inspect()
        self.assertFalse(pending['overwrite_required'])
        self.call('start', device='a')
        self.now = 1
        self.call('stop', device='a')
        before = self.current()
        with self.assertRaisesRegex(ValueError, '轮次.*改变'):
            self.load(pending, overwrite=True)
        self.assertEqual(self.current(), before)


if __name__ == '__main__':
    unittest.main()
