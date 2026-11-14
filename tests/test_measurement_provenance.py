"""Saved signal contracts survive containers and mixed-mode continuation."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from nuclemu.catalog import describe
from nuclemu.core import Session
from nuclemu.exchange import (capture_session, convert_archive, decode_measurement,
    export_item, import_item, load_item, load_package, package_bytes, reopen_session)
from nuclemu.experiments import beta
from nuclemu.web_store import ArchiveStore


SHARED = dict(input=beta.DETECTOR_OUTPUT, consumers=['counter', 'counter_b'])


def old_course():
    current = beta.EXPERIMENT
    return replace(current, devices=tuple(replace(d, input=beta.DETECTOR_OUTPUT) for d in current.devices),
        outputs=(replace(current.outputs[0], response=beta.LEGACY_SHARED_RESPONSE),),
        components=tuple(replace(p, outputs=()) for p in current.components),
        model=beta.sample_shared_counts, restore_definition=None)


def old_document():
    session = Session(old_course(), seed=187)
    session.configure({'source_present': 1})
    session.set_output(beta.DETECTOR_OUTPUT, True)
    session.start(3)
    session.advance(3)
    for device in ('counter', 'counter_b'):
        session.snapshot(device)
    doc = capture_session(session)
    # Exercise the actual historical format, before provenance was recorded.
    for item in doc['items']:
        product = item['document']
        for row in [*product['segments'], *(p for w in product['windows'] for p in w['parts'])]:
            row.pop('signal', None)
    return doc


def target():
    session = Session(beta.EXPERIMENT, seed=187)
    session.configure({'source_present': 1})
    return session


class MeasurementProvenanceTests(unittest.TestCase):
    def assert_shared(self, product):
        for row in [*product['segments'], *(p for w in product.get('windows', ()) for p in w['parts'])]:
            self.assertEqual(row['signal'], SHARED)
        self.assertEqual(sum(sum(s['readings'][product['snapshot']['device']]) for s in product['segments']), 296)
        self.assertEqual(product['snapshot']['exposure_s'], 3)

    def test_separately_transferred_items_keep_shared_contract_without_source_file(self):
        source = old_document()
        before = deepcopy(source)
        for fmt in ('json', 'csv'):
            for original in source['items']:
                with self.subTest(format=fmt, device=original['document']['snapshot']['device']):
                    receiving = capture_session(target())
                    identity = import_item(receiving, source, original['id'])
                    with TemporaryDirectory() as folder:
                        path = Path(folder) / ('transferred.' + fmt)
                        path.write_bytes(export_item(receiving, identity, fmt))
                        restored = load_item(path.read_bytes())
                    item = restored['items'][0]
                    self.assertEqual(item['source'], original['source'])
                    self.assert_shared(item['document'])
                    device = item['document']['snapshot']['device']
                    decoded = decode_measurement(restored, beta.EXPERIMENT, device)
                    self.assertEqual(decoded.snapshot.segments[0].signal.document(), SHARED)
                    # Whole transfers and a second import cannot replace that contract.
                    whole = load_package(package_bytes(receiving))
                    second = capture_session(target())
                    copied = import_item(second, whole, identity)
                    self.assert_shared(load_item(export_item(second, copied, fmt))['items'][0]['document'])
        self.assertEqual(source, before)

    def test_continuation_keeps_shared_prefix_and_new_independent_parts_through_reloads(self):
        source = old_document()
        for fmt in ('json', 'csv'):
            with self.subTest(format=fmt):
                session = target()
                for item in source['items']:
                    device = item['document']['snapshot']['device']
                    decoded = decode_measurement(export_item(source, item['id'], fmt), beta.EXPERIMENT, device)
                    session.load_measurement(device, decoded.snapshot)
                session.set_output(beta.DETECTOR_OUTPUT, True)
                session.start_group(('counter', 'counter_b'))
                session.advance(1)
                for device in ('counter', 'counter_b'):
                    session.snapshot(device)
                with TemporaryDirectory() as folder:
                    path = Path(folder) / 'continued.nuclemu'
                    path.write_bytes(package_bytes(capture_session(session)))
                    doc = load_package(path.read_bytes())
                restored = reopen_session(doc, beta.EXPERIMENT)
                self.assertEqual([s.counts for s in restored.snapshots], [(393,), (401,)])
                again = target()
                for item in doc['items']:
                    device = item['document']['snapshot']['device']
                    bundle = load_item(export_item(doc, item['id'], fmt))
                    product = bundle['items'][0]['document']
                    self.assertEqual(product['segments'][0]['signal'], SHARED)
                    independent = dict(input=beta.DETECTOR_OUTPUT if device == 'counter' else beta.DETECTOR_OUTPUT_B,
                                       consumers=[device])
                    self.assertEqual(product['segments'][1]['signal'], independent)
                    self.assertIsNotNone(product['segments'][0]['origin'])
                    self.assertNotIn('origin', product['segments'][1])
                    self.assertEqual([p['signal'] for w in product['windows'] for p in w['parts']],
                                     [SHARED] * 3 + [independent])
                    decoded = decode_measurement(bundle, beta.EXPERIMENT, device)
                    again.load_measurement(device, decoded.snapshot)
                    again.snapshot(device)
                roundtrip = reopen_session(load_package(package_bytes(capture_session(again))), beta.EXPERIMENT)
                for snapshot in roundtrip.snapshots:
                    self.assertEqual(snapshot.segments[0].signal.document(), SHARED)
                    self.assertEqual(snapshot.segments[-1].signal.consumers, (snapshot.device,))

    def test_already_lost_foreign_context_is_not_inferred_from_receiving_definition(self):
        old = old_document()
        broken = capture_session(target())
        item = deepcopy(old['items'][1])
        item['id'] = str(uuid4())
        broken['items'].append(item)
        for fmt in ('json', 'csv'):
            with self.subTest(format=fmt):
                loaded = load_item(export_item(broken, item['id'], fmt))
                self.assertNotIn('signal', loaded['items'][0]['document']['segments'][0])
                session = target()
                session.load_measurement('counter_b', decode_measurement(loaded, beta.EXPERIMENT, 'counter_b').snapshot)
                session.set_output(beta.DETECTOR_OUTPUT, True)
                session.start(4, device='counter_b')
                session.advance(1)
                session.snapshot('counter_b')
                product = capture_session(session)['items'][0]['document']
                self.assertNotIn('signal', product['segments'][0])
                self.assertEqual(product['segments'][1]['signal']['consumers'], ['counter_b'])

    def test_aggregate_csv_and_sqlite_conversion_preserve_original_bindings(self):
        source = old_document()
        for item in source['items']:
            item['document'].pop('windows')
        receiving = capture_session(target())
        identity = import_item(receiving, source, source['items'][1]['id'])
        self.assert_shared(load_item(export_item(receiving, identity, 'csv'))['items'][0]['document'])
        product = dict(source['items'][0]['document'])
        product.pop('snapshot')
        product['devices'] = {d.id: dict(kind=d.kind, channels=d.channels) for d in old_course().devices}
        product['segments'] = [row for item in source['items'] for row in item['document']['segments']]
        archive = dict(definition=source['definition'], time_s=3, settings=source['configuration']['settings'],
            device='counter', analysis={}, calibrations={}, product=product)
        with TemporaryDirectory() as folder:
            store = ArchiveStore(folder)
            store.write('shared', 'archive', archive)
            converted = convert_archive(Path(folder) / 'workbench.sqlite3', 'shared')
            raw = package_bytes(converted)
        for item in load_package(raw)['items']:
            self.assert_shared(item['document'])
            transferred = capture_session(target())
            identity = import_item(transferred, load_package(raw), item['id'])
            self.assert_shared(load_item(export_item(transferred, identity))['items'][0]['document'])

    def test_equal_counts_do_not_make_different_inputs_or_packages_the_same_source(self):
        course = replace(beta.EXPERIMENT, model=lambda settings, start, end, rng:
            {o.id: (17,) for o in beta.EXPERIMENT.outputs})
        session = Session(course)
        session.set_output(beta.DETECTOR_OUTPUT, True)
        session.start(1)
        session.advance(1)
        for device in ('counter', 'counter_b'):
            session.snapshot(device)
        items = capture_session(session)['items']
        self.assertNotEqual(items[0]['document']['segments'][0]['signal']['input'],
                            items[1]['document']['segments'][0]['signal']['input'])
        first, second = old_document(), old_document()
        self.assertNotEqual(first['items'][0]['source']['package'], second['items'][0]['source']['package'])
        self.assertEqual(first['items'][0]['document'], second['items'][0]['document'])


if __name__ == '__main__':
    unittest.main()
