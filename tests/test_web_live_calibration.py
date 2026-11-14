"""Historical spectrum bindings and live calibration survive separate file state."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Device, Experiment, SignalOutput
from nuclemu.exchange import cache_calibration, import_item, load_package, package_bytes, validate_document
from nuclemu.results import Calibration
from nuclemu.web_portable import open_portable
from nuclemu.web_session import Application


def course():
    peak = tuple(10 if c == 500 else 0 for c in range(1024))
    return Experiment('cal-state', 'Calibration state', '', (),
        tuple(Device(d, 'spectrum', d, 1024, input='detector-' + d) for d in ('a', 'b')),
        lambda settings, start, end, rng: {'detector-' + d: tuple(round(n * (end-start)) for n in peak) for d in ('a', 'b')},
        outputs=tuple(SignalOutput('detector-' + d, d, 1024) for d in ('a', 'b')))


class LiveCalibrationTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.now = 0
        self.definition = course()
        self.app = Application({self.definition.id: self.definition}, folder.name, lambda: self.now)
        self.app.open({'experiment': self.definition.id})
        self.lab = self.app.lab

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.lab.id, action=action, **fields))

    def apply(self, energy, *, save=True):
        state = self.lab.state()
        self.call('calibrate', device=state['device'], calibration_context=state['calibration_context'], points=[0, 0, 1000, energy])
        if save:
            state = self.lab.state()
            result = self.call('cache_calibration', device=state['device'], calibration_context=state['calibration_context'], title=f'cal {energy}')
            return result['cached_calibrations'][-1]['id']

    def measurement(self, device='a'):
        self.call('device', device=device)
        self.call('output', output='detector-' + device, enabled=True)
        self.call('start', device=device, duration=1)
        self.now += 1
        self.app.state()
        self.call('snapshot', device=device)
        return self.lab.state()['snapshots'][-1]['item_id']

    def reopen(self, doc=None):
        path = self.folder / 'cal-state.nuclemu'
        path.write_bytes(self.lab.portable_download()[2] if doc is None else package_bytes(doc))
        self.app.lab = open_portable(path.read_bytes(), {self.definition.id: self.definition}, self.app.store, lambda: self.now)
        self.lab = self.app.lab
        # Reopening is idle with outputs off; explicitly enable these test
        # sources before exercising a new, nonempty 500-channel measurement.
        for device in ('a', 'b'):
            self.call('output', output='detector-' + device, enabled=True)
        return load_package(path)

    def energy_at_500(self):
        state = self.lab.state()
        self.call('calculate_roi', device=state['device'], roi=[500, 500], roi_context=state['roi_context'])
        result = self.lab.state()['roi_result']['readout']
        self.assertGreater(result['roi_counts'], 0)
        self.assertEqual(result['centroid'], 500)
        return result['energy_MeV']

    def saved_six_live_three(self):
        self.apply(6)
        identity = self.measurement()
        live = self.apply(3)
        return identity, live

    def test_default_old_spectrum_current_selection_and_new_round_have_distinct_energies(self):
        identity, live = self.saved_six_live_three()
        doc = self.reopen()
        self.assertEqual(doc['live_calibrations'], {'a': live, 'b': None})
        self.assertEqual(self.energy_at_500(), 3)
        self.call('select', device='a', index=None)
        self.assertEqual(self.lab.state()['calibration']['energy2'], 3)
        self.call('select', device='a', item_id=identity)
        self.assertEqual(self.energy_at_500(), 3)
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertEqual(self.energy_at_500(), 1.5)

    def test_explicit_historical_selection_and_second_save_reopen_preserve_live_reference(self):
        identity, live = self.saved_six_live_three()
        self.call('select', device='a', item_id=identity)
        self.assertEqual(self.energy_at_500(), 3)
        self.reopen()
        self.assertEqual(self.energy_at_500(), 3)
        second = self.reopen()
        self.assertEqual(second['live_calibrations']['a'], live)
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertEqual(self.energy_at_500(), 1.5)

    def test_reapplying_earlier_cached_calibration_and_unrelated_import_do_not_use_last_item(self):
        identity, live = self.saved_six_live_three()
        self.apply(9)
        self.apply(3, save=False)
        other = deepcopy(self.lab.exchange.document)
        other_cal = cache_calibration(other, Calibration(self.definition.id, 'a', 1024, 0, 0, 1000, 12))
        import_item(self.lab.exchange.document, other, other_cal)
        doc = self.reopen()
        self.assertEqual(doc['live_calibrations']['a'], live)
        self.assertEqual(self.energy_at_500(), 3)
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertEqual(self.energy_at_500(), 1.5)

    def test_unsaved_live_calibration_does_not_resurrect_historical_one(self):
        self.apply(6)
        identity = self.measurement()
        self.apply(3, save=False)
        doc = self.reopen()
        self.assertIsNone(doc['live_calibrations']['a'])
        self.assertEqual(self.energy_at_500(), 3)
        self.call('select', device='a', index=None)
        self.assertIsNone(self.lab.state()['calibration'])
        self.call('select', device='a', item_id=identity)
        self.assertEqual(self.energy_at_500(), 3)
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertIsNone(self.energy_at_500())

    def test_uncalibrated_history_does_not_remove_live_calibration(self):
        identity = self.measurement()
        self.apply(3)
        # Preserve an explicitly uncalibrated historical item.
        self.lab.exchange.document['items'][0].pop('calibration_id', None)
        self.reopen()
        self.assertIsNone(self.energy_at_500())
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertEqual(self.energy_at_500(), 1.5)

    def test_multiple_instruments_keep_their_own_live_and_historical_calibrations(self):
        first, live_a = self.saved_six_live_three()
        self.call('device', device='b')
        self.apply(10)
        second = self.measurement('b')
        live_b = self.apply(4)
        self.call('select', device='b', item_id=second)
        doc = self.reopen()
        self.assertEqual(doc['live_calibrations'], {'a': live_a, 'b': live_b})
        self.assertEqual(self.energy_at_500(), 5)
        self.call('device', device='a')
        self.call('select', device='a', item_id=first)
        self.assertEqual(self.energy_at_500(), 3)
        for device, expected in [('a', 1.5), ('b', 2)]:
            self.call('device', device=device)
            self.call('start', device=device, duration=1)
            self.now += 1
            self.app.state()
            self.assertEqual(self.energy_at_500(), expected)

    def test_old_package_native_calibration_fallback_does_not_treat_import_as_live(self):
        identity, live = self.saved_six_live_three()
        doc = load_package(self.lab.portable_download()[2])
        doc.pop('live_calibrations')
        other = deepcopy(doc)
        unrelated = cache_calibration(other, Calibration(self.definition.id, 'a', 1024, 0, 0, 1000, 12))
        import_item(doc, other, unrelated)
        self.reopen(doc)
        self.assertEqual(self.energy_at_500(), 3)
        self.call('start', device='a', duration=1)
        self.now += 1
        self.app.state()
        self.assertEqual(self.energy_at_500(), 1.5)

    def test_live_reference_rejects_wrong_kind_device_missing_id_and_invalid_shape(self):
        identity, live = self.saved_six_live_three()
        doc = load_package(self.lab.portable_download()[2])
        for mapping in ([], {'a': identity}, {'b': live}, {'missing': live}, {'a': 'missing'}):
            with self.subTest(mapping=mapping):
                changed = deepcopy(doc)
                changed['live_calibrations'] = mapping
                with self.assertRaises(ValueError):
                    validate_document(changed)


if __name__ == '__main__':
    unittest.main()
