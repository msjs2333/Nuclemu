"""One explicit ROI calculation freezes its actual spectrum and calibration."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.results import Calibration, roi_centroid
from nuclemu.web_portable import open_portable
from nuclemu.web_session import Application


class SpectrumAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.app = Application(discover(), self.folder.name, lambda: self.now)
        self.app.open(dict(experiment='alpha', seed=187))
        self.lab = self.app.lab

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.lab.id, action=action,
                                                  device='mca', **fields))

    def calculate(self, roi=(900, 929)):
        context = self.app.state()['roi_context']
        return self.call('calculate_roi', roi=list(roi), roi_context=context)['roi_result']

    def start(self):
        self.call('configure', values={'source_present': 1})
        self.call('output', output='alpha_detector', enabled=True)
        self.call('start')

    def calibration(self, energy):
        self.lab.work.apply_calibration(Calibration('alpha', 'mca', 1024, 0, 0, 1000, energy))

    def test_only_explicit_calculation_changes_the_frozen_result(self):
        self.start()
        self.calibration(6)
        self.now = 3
        before = self.app.state()
        self.assertIsNone(before['roi_result'])
        self.assertNotIn('centroid', before['readout'])
        counts = tuple(before['instrument']['counts'])
        result = self.calculate()
        frozen = deepcopy(result)
        self.assertEqual(result['counts'], counts)
        self.assertEqual(result['exposure_s'], 3)
        self.assertEqual(result['readout']['roi_counts'], sum(counts[900:930]))
        self.assertEqual(result['readout']['centroid'], roi_centroid(counts, 900, 929))
        self.assertAlmostEqual(result['readout']['energy_MeV'], result['readout']['centroid'] * .006)
        self.now = 4
        self.call('configure', values={'foil_count': 5})
        self.call('analysis', roi=[764, 794], rate_axis=True)
        self.calibration(3)
        with patch('nuclemu.web_spectrum_analysis.roi_centroid', side_effect=AssertionError('Polling recalculated ROI')):
            for _ in range(3):
                state = self.app.state()
                self.assertEqual(state['roi_result'], frozen)
                self.assertEqual(state['readout']['exposure_s'], 4)
        self.now = 5
        updated = self.calculate((764, 794))
        self.assertNotEqual(updated['id'], frozen['id'])
        self.assertEqual(updated['exposure_s'], 5)
        self.assertEqual(updated['roi'], (764, 794))
        self.assertEqual(updated['calibration']['energy2'], 3)
        self.assertGreater(updated['readout']['roi_counts'], 0)
        self.assertEqual(frozen['calibration']['energy2'], 6)
        self.assertEqual(frozen['counts'], counts)
        self.assertEqual(self.lab.work.session.snapshots, ())

    def test_zero_exposure_empty_roi_and_uncalibrated_centroid_are_valid(self):
        random_state = self.lab.work.session._rng.getstate()
        empty = self.calculate()
        self.assertEqual(empty['counts'], (0,) * 1024)
        self.assertEqual(empty['readout']['roi_counts'], 0)
        self.assertIsNone(empty['readout']['centroid'])
        self.assertIsNone(empty['readout']['energy_MeV'])
        self.assertIsNone(empty['readout']['rate'])
        self.assertEqual(self.lab.work.session._rng.getstate(), random_state)
        self.start()
        self.now = 3
        no_counts = self.calculate((0, 1))
        self.assertEqual(no_counts['exposure_s'], 3)
        self.assertEqual(no_counts['readout']['roi_counts'], 0)
        self.assertIsNone(no_counts['readout']['centroid'])
        peak = self.calculate()
        self.assertGreater(peak['readout']['roi_counts'], 0)
        self.assertIsNotNone(peak['readout']['centroid'])
        self.assertIsNone(peak['readout']['energy_MeV'])
        self.assertIsNone(peak['calibration'])

    def test_saved_spectrum_selection_and_clear_do_not_rewrite_an_analysis(self):
        self.start()
        self.calibration(6)
        self.lab.cache_calibration()
        self.now = 3
        self.call('snapshot')
        identity = self.lab.state()['saved_measurements'][0]['id']
        self.call('select', item_id=identity)
        frozen = deepcopy(self.calculate())
        self.assertEqual(frozen['record_id'], identity)
        self.now = 4
        self.call('select', index=None)
        self.calibration(3)
        self.call('begin_clear')
        request = self.lab.state()['clear_confirmation']
        self.call('finish_clear', token=request['token'], choice='discard')
        self.assertEqual(self.lab.state()['roi_result'], frozen)
        self.call('select', item_id=identity)
        again = self.calculate()
        self.assertEqual(again['counts'], frozen['counts'])
        self.assertEqual(again['calibration'], frozen['calibration'])
        self.assertEqual(again['readout'], frozen['readout'])

    def test_stale_spectrum_and_invalid_bounds_preserve_last_result(self):
        self.start()
        self.now = 3
        frozen = deepcopy(self.calculate())
        context = self.lab.state()['roi_context']
        self.call('begin_clear')
        request = self.lab.state()['clear_confirmation']
        self.call('finish_clear', token=request['token'], choice='discard')
        with self.assertRaisesRegex(ValueError, '所选谱或采集轮次'):
            self.call('calculate_roi', roi=[900, 929], roi_context=context)
        for bounds in ([-1, 4], [0, 1024], [10, 9], [True, 3], [1.5, 3], [1], None):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ValueError, '有效道址'):
                self.call('calculate_roi', roi=bounds, roi_context=self.lab.state()['roi_context'])
        self.assertEqual(self.lab.state()['roi_result'], frozen)

    def test_saved_identity_context_is_checked_and_file_reopen_has_no_stale_result(self):
        self.start()
        self.calibration(6)
        self.lab.cache_calibration()
        self.now = 3
        self.call('snapshot')
        context = self.lab.state()['roi_context']
        self.now = 4
        self.call('snapshot')
        identities = [item['id'] for item in self.lab.state()['saved_measurements']]
        self.call('select', item_id=identities[0])
        with self.assertRaisesRegex(ValueError, '所选谱或采集轮次'):
            self.call('calculate_roi', roi=[900, 929], roi_context=context)
        frozen = deepcopy(self.calculate())
        context = self.lab.state()['roi_context']
        self.call('select', item_id=identities[1])
        with self.assertRaisesRegex(ValueError, '所选谱或采集轮次'):
            self.call('calculate_roi', roi=[900, 929], roi_context=context)
        self.assertEqual(self.lab.state()['roi_result'], frozen)
        path = Path(self.folder.name) / 'roi-source.nuclemu'
        path.write_bytes(self.lab.portable_download()[2])
        reopened = open_portable(path.read_bytes(), self.app.definitions, self.lab.store, lambda: self.now)
        self.assertIsNone(reopened.state()['roi_result'])
        reopened.act(dict(action='select', device='mca', item_id=identities[0]))
        reopened.act(dict(action='calculate_roi', device='mca', roi=[900, 929],
                          roi_context=reopened.state()['roi_context']))
        recalculated = reopened.state()['roi_result']
        self.assertEqual(recalculated['counts'], frozen['counts'])
        self.assertEqual(recalculated['calibration'], frozen['calibration'])
        self.assertEqual(recalculated['readout'], frozen['readout'])

    def test_empty_source_keeps_zero_spectrum_with_exposure_and_no_fake_background(self):
        self.call('output', output='alpha_detector', enabled=True)
        self.call('start')
        self.now = 3600
        result = self.calculate((0, 1023))
        self.assertEqual(result['exposure_s'], 3600)
        self.assertEqual(sum(result['counts']), 0)
        self.assertIsNone(result['readout']['centroid'])


if __name__ == '__main__':
    unittest.main()
