"""Background independence follows each contributing measurement's provenance."""

from copy import deepcopy
from base64 import b64encode
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import capture_session, decode_measurement, export_item, package_bytes, load_package, save_package
from nuclemu.results import net_count_rate
from nuclemu.web_import import apply_import, inspect_import
from nuclemu.web_session import Application
from nuclemu.web_portable import open_portable


class LoadedBackgroundOverlapTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.definition = discover()['beta']
        self.now = 0
        self.app = Application({'beta': self.definition}, self.directory.name, clock=lambda: self.now)
        self.app.open({'experiment': 'beta', 'seed': 0})
        self.lab = self.app.lab
        self.work = self.lab.work

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.lab.id, action=action, **fields))

    def native_background(self):
        self.call('output', output='beta_detector', enabled=True)
        self.call('start', device='counter', duration=3)
        self.now = 3
        self.call('snapshot', device='counter')
        self.assertEqual(self.work.lab.source, self.lab.exchange.document['id'])
        return self.work.session.snapshots[0]

    def web_load_and_extend(self, raw=None):
        fields = {} if raw is None else {'file': b64encode(raw).decode()}
        pending = self.app.request('/api/inspect_measurement',
                                   dict(session=self.lab.id, device='counter', **fields))
        self.call('load_measurement', token=pending['token'], item_id=pending['items'][0]['id'], overwrite=True)
        self.call('configure', values={'source_present': 1})
        self.call('instrument_config', device='counter', duration_s=None)
        started = self.call('start', device='counter')
        self.now = 4
        self.call('stop', device='counter', acquisition=started['active_acquisition'],
                  cycle=started['instrument']['cycle'])
        self.work.set_background(0)

    def test_web_native_cache_load_is_linked_to_the_same_session(self):
        self.native_background()
        self.web_load_and_extend()
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()
        self.assertIn('net_rate', self.work.readout_for(1))

    def test_web_native_json_load_is_linked_to_the_same_session(self):
        self.native_background()
        document = self.lab.exchange.document
        raw = export_item(document, document['items'][0]['id'], 'json')
        self.web_load_and_extend(raw)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()
        self.assertIn('net_rate', self.work.readout_for(1))

    def test_web_native_csv_load_is_linked_to_the_same_session(self):
        self.native_background()
        document = self.lab.exchange.document
        raw = export_item(document, document['items'][0]['id'], 'csv')
        self.web_load_and_extend(raw)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()
        self.assertIn('net_rate', self.work.readout_for(1))

    def test_web_foreign_prefix_is_independent_of_known_local_background(self):
        reference = self.native_background()
        foreign, saved = self.source()
        self.assertNotEqual(foreign['id'], self.work.lab.source)
        self.web_load_and_extend(export_item(foreign, foreign['items'][0]['id']))
        current = self.work.readout()
        new = self.work.readout_for(1)
        self.assertEqual(current['counts'], saved.counts[0] + new['counts'])
        self.assertEqual((current['net_rate'], current['uncertainty']),
                         net_count_rate(current['counts'], 4, reference.counts[0], 3))

    def source(self, *, seed=2, duration=3):
        session = Session(self.definition, seed=seed)
        session.set_output('beta_detector', True)
        session.start(duration, device='counter')
        session.advance(duration)
        snapshot = session.snapshot('counter')
        return capture_session(session), snapshot

    def import_reference(self, document):
        pending = inspect_import(self.lab, package_bytes(document))
        result = apply_import(self.lab, pending['token'], document['items'][0]['id'])
        index, = self.work.lab.view.item_indices[result['id']]
        self.work.set_background(index)
        return index

    def load_and_extend(self, document):
        item = document['items'][0]
        decoded = decode_measurement(document, self.definition, 'counter', item['id'])
        self.work.session.load_measurement('counter', decoded.snapshot)
        self.work.configure({'source_present': 1})
        self.work.set_output('beta_detector', True)
        self.work.start(device='counter')
        self.work.advance(1)

    def test_imported_background_loaded_and_extended_is_not_independent(self):
        document, saved = self.source()
        original = deepcopy(document)
        self.assertEqual(saved.exposure_s, 3)
        self.import_reference(document)
        self.load_and_extend(document)
        current = self.work.session.instrument('counter')
        self.assertEqual(current.exposure_s, 4)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()
        # This truly new one-second segment has a different live origin even
        # though its physical coordinates overlap the imported file's 0..3s.
        sample = self.work.readout_for(1)
        self.assertEqual(sample['exposure_s'], 1)
        self.assertEqual(current.counts[0], saved.counts[0] + sample['counts'])
        self.assertEqual((sample['net_rate'], sample['uncertainty']),
                         net_count_rate(sample['counts'], 1, saved.counts[0], 3))
        self.assertEqual(document, original)

    def test_same_clock_coordinates_from_different_packages_are_independent(self):
        reference, background = self.source()
        independent, _ = self.source(seed=8)
        self.import_reference(reference)
        self.load_and_extend(independent)
        counts = self.work.session.instrument('counter').counts[0]
        result = self.work.readout()
        self.assertEqual((result['net_rate'], result['uncertainty']), net_count_rate(counts, 4, background.counts[0], 3))

    def test_switching_to_an_independent_background_does_not_change_raw_counts(self):
        source, _ = self.source()
        first = self.import_reference(source)
        self.load_and_extend(source)
        other, other_snapshot = self.source(seed=0)
        second = self.import_reference(other)
        self.work.select(None)
        before = self.work.session.instrument('counter')
        corrected = self.work.readout()
        self.assertEqual((corrected['net_rate'], corrected['uncertainty']),
                         net_count_rate(before.counts[0], 4, other_snapshot.counts[0], 3))
        self.work.set_background(first)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()
        self.work.set_background(second)
        self.assertEqual(self.work.readout(), corrected)
        self.assertEqual(self.work.session.instrument('counter'), before)

    def test_native_cached_background_without_package_binding_is_not_assumed_independent(self):
        self.work.set_output('beta_detector', True)
        self.work.start(3, device='counter')
        self.work.advance(3)
        background = self.work.snapshot(device='counter')
        document = capture_session(self.work.session)
        decoded = decode_measurement(document, self.definition, 'counter', document['items'][0]['id'])
        self.work.session.load_measurement('counter', decoded.snapshot, overwrite=True)
        self.work.configure_acquisition(device='counter', duration_s=None)
        self.work.configure({'source_present': 1})
        self.work.start(device='counter')
        self.work.advance(1)
        self.work.set_background(0)
        with self.assertRaisesRegex(ValueError, 'source|nonoverlapping'):
            self.work.readout()
        sample = self.work.readout_for(1)
        self.assertEqual(sample['exposure_s'], 1)
        expected = net_count_rate(sample['counts'], 1, background.counts[0], 3)
        self.assertEqual((sample['net_rate'], sample['uncertainty']), expected)

    def test_overlapping_cumulative_item_in_the_same_package_is_rejected(self):
        source = Session(self.definition, seed=2)
        source.set_output('beta_detector', True)
        source.start(device='counter')
        source.advance(3)
        source.snapshot('counter')
        source.advance(2)
        source.snapshot('counter')
        document = capture_session(source)
        self.import_reference(document)
        second = document['items'][1]
        loaded = decode_measurement(document, self.definition, 'counter', second['id'])
        self.work.session.load_measurement('counter', loaded.snapshot)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()

    def test_different_explicit_opaque_origins_do_not_share_a_colon_namespace(self):
        document, _ = self.source()
        reference_index = self.import_reference(document)
        self.load_and_extend(document)
        reference = self.work.product()['segments'][reference_index]
        sample = self.work.product()['segments'][1]
        reference['origin'], sample['origin'] = 'custom:reference', 'custom:sample'
        self.assertIn('net_rate', self.work.readout_for(1))
        sample['origin'] = 'custom:reference'
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout_for(1)

    def test_explicit_segment_origin_overrides_the_container_package(self):
        document, _ = self.source()
        self.import_reference(document)
        self.load_and_extend(document)
        snapshot = self.work.snapshot(cache=False)
        # The imported prefix's explicit origin survives a later packaging;
        # it must not be mistaken for the newly chosen container identity.
        self.work.lab.view.package_id = 'another-container'
        self.assertEqual(snapshot.segments[0].origin,
                         document['id'] + ':' + document['items'][0]['id'])
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            self.work.readout()

    def test_overlap_survives_real_package_save_reopen_and_another_load(self):
        document, background = self.source()
        self.import_reference(document)
        self.load_and_extend(document)
        self.work.snapshot(device='counter')
        combined = capture_session(self.work.session, self.lab.exchange.document)
        path = self.directory.name + '/loaded-and-extended.nuclemu'
        save_package(path, combined)
        saved = load_package(path)
        self.assertEqual(saved['items'], combined['items'])
        reopened = open_portable(package_bytes(saved), {'beta': self.definition},
                                 self.lab.store, lambda: 0)
        reopened.work.set_background(0)
        accumulated = saved['items'][-1]
        decoded = decode_measurement(saved, self.definition, 'counter', accumulated['id'])
        reopened.work.session.load_measurement('counter', decoded.snapshot)
        with self.assertRaisesRegex(ValueError, 'nonoverlapping'):
            reopened.work.readout()
        # A new container and another load do not make the prefix independent,
        # or make the newly observed suffix dependent on that old reference.
        index = reopened.work.lab.view.item_indices[accumulated['id']][-1]
        suffix = reopened.work.readout_for(index)
        self.assertEqual((suffix['net_rate'], suffix['uncertainty']),
                         net_count_rate(suffix['counts'], 1, background.counts[0], 3))


if __name__ == '__main__':
    unittest.main()
