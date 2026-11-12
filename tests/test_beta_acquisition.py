"""The real beta course routes one detector into independently exposed counters."""

from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json
import math
from random import Random
from tempfile import TemporaryDirectory
import unittest

from examples.beta_windows import background_comparison, counts, dual_windows
from nuclemu.catalog import describe
from nuclemu.core import Device, Parameter, Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT, sample_counts
from nuclemu.physics import AluminumFoil
from nuclemu.results import MeasurementView, write_product


class BetaAcquisitionTests(unittest.TestCase):
    def test_source_foil_output_and_two_readout_bindings(self):
        entry = describe(EXPERIMENT)
        parts = {p['id']: p for p in entry['components']}
        self.assertEqual(parts['source']['parameters'], ('source_present',))
        self.assertEqual(set(parts['foil']['parameters']), {'foil_spec_um', 'foil_count'})
        self.assertEqual(parts['detector']['output'], DETECTOR_OUTPUT)
        self.assertIsNone(parts['detector']['device'])
        self.assertEqual([d.input for d in EXPERIMENT.devices], [DETECTOR_OUTPUT] * 2)
        self.assertEqual([d.channels for d in EXPERIMENT.devices], [1, 1])

    def test_foil_specs_empty_and_equivalent_stacks(self):
        for spec in (50, 100):
            for number in (0, 1, 24):
                foil = AluminumFoil(spec * number / 1000)
                self.assertAlmostEqual(foil.areal_density_g_cm2, spec * number * 1e-4 * 2.70)
        first = {'source_present': 1, 'foil_count': 2, 'foil_spec_um': 50}
        second = {'source_present': 1, 'foil_count': 1, 'foil_spec_um': 100}
        self.assertEqual(sample_counts(first, 0, 10, Random(42)), sample_counts(second, 0, 10, Random(42)))
        empty = {'source_present': 0, 'foil_count': 24, 'foil_spec_um': 100}
        self.assertEqual(sample_counts(empty, 0, 10, Random(42)),
                         sample_counts(dict(empty, foil_count=0), 0, 10, Random(42)))
        session = Session(EXPERIMENT)
        for key, value in (('foil_spec_um', 75), ('foil_count', 25), ('source_present', 2)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                session.set(key, value)

    def test_shared_5_plus_5_equals_10_at_multiple_foil_conditions(self):
        for spec, foils in ((50, 0), (50, 8), (100, 4), (100, 24)):
            with self.subTest(spec=spec, foils=foils):
                s = Session(EXPERIMENT, seed=42)
                s.set('foil_spec_um', spec); s.set('foil_count', foils)
                s.set_output(DETECTOR_OUTPUT, True)
                s.start(5, device='counter'); s.start(10, device='counter_b')
                s.advance(5)
                first = counts(s, 'counter')
                self.assertEqual(first, counts(s, 'counter_b'))
                self.assertFalse(s.instrument('counter').running)
                self.assertTrue(s.instrument('counter_b').running)
                s.snapshot('counter'); s.clear(device='counter')
                s.start(5, device='counter'); s.advance(5)
                self.assertEqual(counts(s, 'counter'), counts(s, 'counter_b'))
                left = [r for r in s.records if 'counter' in r.readings]
                right = [r for r in s.records if 'counter_b' in r.readings]
                self.assertEqual([r.readings['counter'][0] for r in left],
                                 [r.readings['counter_b'][0] for r in right])
                self.assertEqual(sum(r.exposure_s for r in left), 10)
                self.assertEqual(sum(r.exposure_s for r in right), 10)

    def test_a_stops_while_b_continues_and_export_exposures_stay_separate(self):
        result = dual_windows(reopen=False)
        self.assertEqual((result['A_first_5s'], result['A_second_5s'], result['B_10s']), (279, None, 550))
        for device, duration, count in (('counter', 5, 279), ('counter_b', 10, 550)):
            stream = StringIO()
            write_product(stream, 'json', result['product'], device=device)
            segment, = json.loads(stream.getvalue())['segments']
            self.assertEqual(segment['end_s'] - segment['start_s'], duration)
            self.assertEqual(segment['readings'], {device: [count]})

    def test_empty_source_keeps_background_but_output_off_is_zero_input(self):
        s = Session(EXPERIMENT, seed=42)
        s.advance(10)
        self.assertEqual(s.time_s, 0)
        s.set('source_present', 0)
        s.set_output(DETECTOR_OUTPUT, True)
        s.start(19.5, device='counter'); s.advance(19.5)
        self.assertEqual(counts(s, 'counter'), 32)
        s.set_output(DETECTOR_OUTPUT, False)
        s.start(2, device='counter_b'); s.advance(10)
        self.assertEqual(s.instrument('counter_b').exposure_s, 2)
        self.assertEqual(counts(s, 'counter_b'), 0)
        self.assertEqual(s.time_s, 21.5)
        self.assertFalse(s.clock_running)

    def test_detector_off_middle_preserves_exposure_and_disjoint_counts(self):
        s = Session(EXPERIMENT, seed=42)
        s.set_output(DETECTOR_OUTPUT, True)
        s.start(10)
        s.advance(3); s.set_output(DETECTOR_OUTPUT, False)
        s.advance(4); s.set_output(DETECTOR_OUTPUT, True)
        s.advance(3)
        for device in ('counter', 'counter_b'):
            rows = [r for r in s.records if device in r.readings]
            self.assertEqual(sum(r.exposure_s for r in rows), 10)
            middle = [r for r in rows if 3 <= r.start_s and r.end_s <= 7]
            self.assertEqual(sum(r.exposure_s for r in middle), 4)
            self.assertTrue(all(r.readings[device] == (0,) for r in middle))
        self.assertEqual(counts(s, 'counter'), counts(s, 'counter_b'))

    def test_background_selection_changes_only_analysis_with_unequal_exposures(self):
        result = background_comparison()
        product = deepcopy(result['product'])
        self.assertEqual([s['readings']['counter'][0] for s in product['segments']], [32, 399, 20])
        for reading, nb, tb in zip(result['comparisons'], (32, 20), (19.5, 9.25)):
            self.assertEqual((reading['counts'], reading['exposure_s']), (399, 7.25))
            self.assertAlmostEqual(reading['net_rate'], 399 / 7.25 - nb / tb)
            self.assertAlmostEqual(reading['uncertainty'], math.sqrt(399 / 7.25**2 + nb / tb**2))
        self.assertEqual(result['product'], product)
        self.assertEqual([s['counts'][0] for s in result['saved_windows']], [32, 399, 20])

    def test_legacy_beta_archive_reads_its_own_settings_and_single_instrument(self):
        from nuclemu.web_session import WebLab
        from nuclemu.web_store import ArchiveStore
        old = replace(EXPERIMENT,
            parameters=(Parameter('source_present', '测量模式', '', 1, 0, 1, True),
                        Parameter('foil_count', '铝箔片数', '片', 0, 0, 24, True)),
            devices=(Device('counter', 'counter', 'β 计数器'),),
            outputs=(), components=(), connections=(),
            model=lambda settings, start, end, rng:
                {'counter': sample_counts(settings, start, end, rng)[DETECTOR_OUTPUT]})
        info = describe(old)
        info.pop('outputs', None)
        info['devices'][0].pop('input', None)
        with TemporaryDirectory() as folder:
            store = ArchiveStore(folder)
            lab = WebLab(old, info, 42, store, lambda: 0)
            lab.work.configure({'foil_count': 4})
            lab.work.start(1.25); lab.work.advance(1.25)
            document = deepcopy(lab.document())
            store.write('legacy-beta', 'archive', document)
            restored = WebLab.read('legacy-beta', store, lambda: 100)
            state = restored.state()
            self.assertTrue(state['readonly'])
            self.assertEqual(state['product'], document['product'])
            self.assertEqual(state['settings'], {'source_present': 1, 'foil_count': 4})
            self.assertNotIn('foil_spec_um', state['settings'])
            self.assertEqual([d.id for d in restored.work.session.experiment.devices], ['counter'])
            self.assertEqual(state['output_enabled'], {})

    def test_refresh_chunking_does_not_change_the_same_gate_timeline(self):
        def run(chunk):
            s = Session(EXPERIMENT, seed=42)
            s.set('foil_count', 4); s.set_output(DETECTOR_OUTPUT, True)
            s.start(5, device='counter'); s.start(10, device='counter_b')
            view = MeasurementView(s)
            for _ in range(2):
                for _ in range(round(5 / chunk)):
                    s.advance(chunk); view.product()
                if s.time_s == 5:
                    s.snapshot('counter'); s.clear(device='counter'); s.start(5, device='counter')
            return s.records
        self.assertEqual(run(5), run(.1))


if __name__ == '__main__':
    unittest.main()
