"""Loaded saved spectra retain their saved calibration through new saves."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import (bind_calibration, cache_calibration, capture_session,
                              decode_measurement, export_item, load_item, load_package)
from nuclemu.results import Calibration
from nuclemu.web_import import apply_import, inspect_import
from nuclemu.web_measurement import inspect_measurement
from nuclemu.web_portable import open_portable
from nuclemu.web_session import Application


class LoadedCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.definitions = discover()
        self.definition = self.definitions['alpha']
        session = Session(self.definition, seed=33)
        session.configure({'source_present': 1})
        session.set_output('alpha_detector', True)
        session.start(3, device='mca')
        session.advance(3)
        session.snapshot('mca')
        self.source = capture_session(session)
        self.calibration = Calibration('alpha', 'mca', 1024, 0, 0, 1000, 6)
        identity = cache_calibration(self.source, self.calibration)
        bind_calibration(self.source, self.source['items'][0]['id'], identity)
        self.cal_source = self.source['items'][1]['source']

    def fresh(self):
        app = Application(self.definitions, self.folder.name, lambda: 0)
        app.open({'experiment': 'alpha', 'seed': 42})
        return app.lab

    def load(self, lab, fmt, route):
        identity = self.source['items'][0]['id']
        path = Path(self.folder.name) / ('source.' + fmt)
        path.write_bytes(export_item(self.source, identity, fmt))
        if route == 'cache':
            pending = inspect_import(lab, path.read_bytes())
            identity = apply_import(lab, pending['token'], identity)['id']
            pending = inspect_measurement(lab, 'mca')
        else:
            pending = inspect_measurement(lab, 'mca', path.read_bytes())
        lab.act(dict(action='load_measurement', token=pending['token'], item_id=identity,
                     overwrite=pending['overwrite_required']))

    def assert_downloads(self, lab, expected):
        path = Path(self.folder.name) / 'saved.nuclemu'
        path.write_bytes(lab.portable_download()[2])
        document = load_package(path.read_bytes())
        measurement = next(item for item in reversed(document['items'])
                           if item['kind'] == 'measurement' and item['source']['package'] == document['id'])
        self.assertIn('calibration_id', measurement)
        calibration = next(item for item in document['items']
                           if item['id'] == measurement['calibration_id'])
        self.assertEqual(calibration['source'], self.cal_source)
        reopened = open_portable(path.read_bytes(), self.definitions, lab.store, lambda: 0)
        reopened.act(dict(action='select', device='mca', item_id=measurement['id']))
        reopened.act(dict(action='analysis', device='mca', roi=[900, 929]))
        reopened.act(dict(action='calculate_roi', device='mca', roi=[900, 929],
                          roi_context=reopened.state()['roi_context']))
        whole_energy = reopened.state()['roi_result']['readout']['energy_MeV']
        self.assertIsNotNone(whole_energy)
        for fmt in ('json', 'csv'):
            with self.subTest(download=fmt):
                path = Path(self.folder.name) / ('saved.' + fmt)
                path.write_bytes(lab.portable_download([dict(id=measurement['id'], format=fmt)])[2])
                bundle = load_item(path.read_bytes())
                decoded = decode_measurement(bundle, self.definition, 'mca')
                self.assertEqual((decoded.snapshot.counts, decoded.snapshot.exposure_s), expected)
                self.assertEqual(decoded.calibration, self.calibration)
                result = reopened.work.readout_snapshot(decoded.snapshot, 900, 929,
                                                        calibration=decoded.calibration)
                self.assertAlmostEqual(result['energy_MeV'], whole_energy)

    def test_file_and_cache_load_save_continue_and_clear_keep_calibration(self):
        for fmt in ('json', 'csv'):
            for route in ('file', 'cache'):
                for operation in ('save', 'continue', 'clear'):
                    with self.subTest(fmt=fmt, route=route, operation=operation):
                        lab = self.fresh()
                        self.load(lab, fmt, route)
                        if operation == 'continue':
                            lab.work.configure({'source_present': 1})
                            lab.work.set_output('alpha_detector', True)
                            lab.work.start(4, device='mca')
                            lab.work.advance(1)
                        instrument = lab.work.session.instrument('mca')
                        expected = instrument.counts, instrument.exposure_s
                        self.assertEqual(expected[1], 4 if operation == 'continue' else 3)
                        if operation == 'clear':
                            lab.act(dict(action='begin_clear', device='mca'))
                            pending = lab.state()['clear_confirmation']
                            lab.act(dict(action='finish_clear', device='mca', token=pending['token'], choice='save'))
                            self.assertEqual(lab.work.session.instrument('mca').exposure_s, 0)
                        else:
                            lab.act(dict(action='snapshot', device='mca'))
                        self.assert_downloads(lab, expected)

    def test_new_applied_calibration_still_requires_explicit_save(self):
        lab = self.fresh()
        lab.work.apply_calibration(self.calibration)
        lab.work.start(1, device='mca')
        lab.work.advance(1)
        lab.act(dict(action='snapshot', device='mca'))
        document = load_package(lab.portable_download()[2])
        self.assertFalse(any(item['kind'] == 'calibration' for item in document['items']))
        self.assertNotIn('calibration_id', document['items'][0])

    def test_equal_calibrations_keep_loaded_provenance_without_duplicate_copies(self):
        lab = self.fresh()
        self.load(lab, 'json', 'file')
        lab.work.apply_calibration(self.calibration)
        lab.cache_calibration()
        # The most recently cached equal calibration has a different source.
        self.assertNotEqual(lab.exchange.document['items'][-1]['source'], self.cal_source)
        self.load(lab, 'json', 'file')
        self.assertEqual(sum(item['kind'] == 'calibration' for item in lab.exchange.document['items']), 2)
        lab.act(dict(action='snapshot', device='mca'))
        instrument = lab.work.session.instrument('mca')
        self.assert_downloads(lab, (instrument.counts, instrument.exposure_s))

    def test_calibration_names_are_explicit_and_invalid_names_publish_nothing(self):
        lab = self.fresh()
        lab.work.apply_calibration(self.calibration)
        for title in ('', '   ', False, 12):
            with self.subTest(title=title), self.assertRaises(ValueError):
                lab.act(dict(action='cache_calibration', device='mca', title=title,
                             calibration_context=lab.calibration_context()))
            self.assertIsNone(lab.exchange.document)
            self.assertEqual(lab.work.lab.calibrations['mca'], self.calibration)
        lab.act(dict(action='cache_calibration', device='mca', title='  我的能量刻度  ',
                     calibration_context=lab.calibration_context()))
        item = lab.exchange.document['items'][0]
        self.assertEqual(item['title'], '我的能量刻度')
        self.assertEqual(item['document'], self.calibration.document())
        bundle = load_item(lab.portable_download([dict(id=item['id'], format='json')])[2])
        self.assertEqual(bundle['items'][0], item)
        document = load_package(lab.portable_download()[2])
        self.assertEqual(document['items'][0], item)


if __name__ == '__main__':
    unittest.main()
