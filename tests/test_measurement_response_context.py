"""Input and response provenance survives changing containers, never guessed."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Device, Experiment, Session, SignalOutput
from nuclemu.exchange import (capture_session, decode_measurement, export_item, import_item,
    load_item, load_package, measurement_response_context, package_bytes, validate_document)


OLD = Experiment('response', 'Response', '', (), (Device('a', 'counter', 'A', input='out'),),
    lambda settings, start, end, rng: {'out': (round(10*(end-start)),)},
    outputs=(SignalOutput('out', 'Output', response='old fixed response'),))
CURRENT = replace(OLD, outputs=(replace(OLD.outputs[0], response='current fixed response'),))


def saved(course):
    s = Session(course)
    s.set_output('out', True)
    s.start(device='a')
    s.advance(1)
    s.snapshot('a')
    return capture_session(s)


class MeasurementResponseContextTests(unittest.TestCase):
    def test_old_native_contract_survives_import_and_actual_reexport_files(self):
        original = saved(OLD)
        self.assertEqual(original['items'][0]['response_context'], dict(input='out', response='old fixed response'))
        original['items'][0].pop('response_context')
        with TemporaryDirectory() as folder:
            for fmt in ('json', 'csv', 'nuclemu'):
                with self.subTest(format=fmt):
                    raw = package_bytes(original) if fmt == 'nuclemu' else export_item(original, original['items'][0]['id'], fmt)
                    path = Path(folder) / ('old.' + fmt)
                    path.write_bytes(raw)
                    source = load_package(path) if fmt == 'nuclemu' else load_item(path)
                    target = capture_session(Session(CURRENT))
                    identity = import_item(target, source, source['items'][0]['id'])
                    for out_fmt in ('json', 'csv'):
                        path = Path(folder) / ('reexported.' + out_fmt)
                        path.write_bytes(export_item(target, identity, out_fmt))
                        item = load_item(path)['items'][0]
                        self.assertEqual(measurement_response_context(item, target['definition'], target['id']),
                                         dict(input='out', response='old fixed response'))

    def test_foreign_unknown_and_mixed_loaded_prefix_never_infer_current_response(self):
        source = saved(OLD)
        source['items'][0].pop('response_context')
        target = capture_session(Session(CURRENT))
        target['items'] = deepcopy(source['items'])
        item = target['items'][0]
        self.assertIsNone(measurement_response_context(item, target['definition'], target['id']))
        for fmt in ('json', 'csv'):
            self.assertNotIn('response_context', load_item(export_item(target, item['id'], fmt))['items'][0])
        s = Session(CURRENT)
        s.load_measurement('a', decode_measurement(source, CURRENT, 'a').snapshot)
        s.set_output('out', True)
        s.start(device='a')
        s.advance(1)
        s.snapshot('a')
        self.assertNotIn('response_context', capture_session(s)['items'][0])

    def test_malformed_context_is_rejected_at_file_boundary(self):
        for context in (None, {}, {'input': 'out', 'response': 1}, {'input': '', 'response': 'known'}):
            with self.subTest(context=context):
                doc = saved(OLD)
                doc['items'][0]['response_context'] = context
                with self.assertRaisesRegex(ValueError, 'response context'):
                    validate_document(doc)


if __name__ == '__main__':
    unittest.main()
