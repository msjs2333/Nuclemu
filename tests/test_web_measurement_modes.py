"""Continuation notices follow the selected saved measurement across containers."""
from base64 import b64encode
from copy import deepcopy
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from nuclemu.core import Session
from nuclemu.exchange import capture_session, export_item, import_item, load_item, package_bytes
from nuclemu.experiments import beta
from nuclemu.web_session import Application
from test_measurement_provenance import old_document


def independent_document():
    current = beta.EXPERIMENT
    course = replace(current, outputs=tuple(replace(o, response=r) for o, r in
        zip(current.outputs, beta.LEGACY_INDEPENDENT_RESPONSES)),
        model=beta._previous_independent_counts, restore_definition=None)
    session = Session(course, seed=187)
    session.configure({'source_present': 1})
    session.set_output(beta.DETECTOR_OUTPUT, True)
    session.start(1)
    session.advance(1)
    session.snapshot('counter')
    return capture_session(session)


def current_document():
    session = Session(beta.EXPERIMENT, seed=187)
    session.set_output(beta.DETECTOR_OUTPUT, True)
    session.start(1)
    session.advance(1)
    session.snapshot('counter')
    return capture_session(session)


class MeasurementModeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = Application({'beta': beta.EXPERIMENT}, self.folder.name, lambda: 0)
        self.app.open({'experiment': 'beta', 'seed': 187})

    def inspect(self, raw=None):
        return self.app.request('/api/inspect_measurement', dict(session=self.app.lab.id,
            component='counter', **({'file': b64encode(raw).decode()} if raw is not None else {})))

    def test_shared_independent_unknown_and_current_agree_after_import_and_reexport(self):
        unknown = current_document()
        foreign = deepcopy(old_document()['items'][1])
        foreign.pop('response_context', None)
        for segment in foreign['document']['segments']:
            segment.pop('signal', None)
        unknown['items'] = [foreign]
        for name, doc in [('shared', old_document()), ('independent', independent_document()),
                          ('unknown', unknown), ('current', current_document())]:
            item = doc['items'][-1]
            identity = item['id']
            for fmt in ('json', 'csv', 'whole'):
                with self.subTest(mode=name, format=fmt):
                    folder = TemporaryDirectory()
                    self.addCleanup(folder.cleanup)
                    self.app = Application({'beta': beta.EXPERIMENT}, folder.name, lambda: 0)
                    self.app.open({'experiment': 'beta', 'seed': 187})
                    raw = package_bytes(doc) if fmt == 'whole' else export_item(doc, identity, fmt)
                    before = self.app.lab.work.session.instrument(item['document']['snapshot']['device'])
                    pending = self.inspect(raw)
                    direct = next(row for row in pending['items'] if row['id'] == identity)['notice']
                    self.assertEqual(self.app.lab.work.session.instrument(before.device), before)
                    if name == 'current':
                        self.assertEqual(direct, '')
                    else:
                        self.assertIn('继续测量使用当前课程的独立双窗响应', direct)
                        self.assertIn('原有计数与实际曝光保留', direct)
                        self.assertIn('来源响应不详' if name == 'unknown' else '版本与当前课程不同', direct)
                    target = capture_session(self.app.lab.work.session)
                    copied = import_item(target, load_item(raw) if fmt != 'whole' else doc, identity)
                    self.app.lab.exchange.document = target
                    cached = self.inspect()
                    self.assertEqual(next(row['notice'] for row in cached['items'] if row['id'] == copied), direct)
                    for outgoing in ('json', 'csv'):
                        again = self.inspect(export_item(target, copied, outgoing))
                        self.assertEqual(again['items'][0]['notice'], direct)

    def test_choice_notices_are_per_record_and_loading_preserves_old_counts(self):
        old = independent_document()
        self.assertEqual(sum(s['readings']['counter'][0] for s in old['items'][0]['document']['segments']), 97)
        target = current_document()
        copied = import_item(target, old, old['items'][0]['id'])
        self.app.lab.exchange.document = target
        pending = self.inspect()
        notices = {r['id']: r['notice'] for r in pending['items']}
        self.assertEqual(notices[target['items'][0]['id']], '')
        self.assertIn('版本与当前课程不同', notices[copied])
        self.app.request('/api/action', dict(session=self.app.lab.id, action='load_measurement',
            token=pending['token'], item_id=copied))
        value = self.app.lab.work.session.instrument('counter')
        self.assertEqual((value.counts, value.readable_exposure_s), ((97,), 1))


if __name__ == '__main__': unittest.main()
