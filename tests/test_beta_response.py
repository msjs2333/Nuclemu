"""Course response, equal areal density, and saved-response continuation."""
from copy import deepcopy
from random import Random
import unittest

from nuclemu.catalog import describe
from nuclemu.core import Session
from nuclemu.exchange import capture_session, decode_measurement, export_item, load_package, package_bytes, reopen_session
from nuclemu.experiments import beta


def previous_definition():
    info = describe(beta.EXPERIMENT)
    for output, response in zip(info['outputs'], beta.LEGACY_INDEPENDENT_RESPONSES):
        output['response'] = response
    return beta.restore_definition(info)


class BetaResponseTests(unittest.TestCase):
    def test_total_net_rates_at_operable_thicknesses_and_equal_mass_stacks(self):
        for count, total in ((0, 11650), (1, 4999.843031), (2, 2655.591528),
                             (4, 1452.010503), (8, 1046.788279), (14, 746.573058)):
            # Published table rounding is checked against an independently
            # written two-component expression at the actual foil mass.
            settings = dict(source_present=1, foil_spec_um=100, foil_count=count)
            rates = beta.expected_rates(settings)
            self.assertAlmostEqual(rates['areal_density_g_cm2'], .027*count)
            self.assertAlmostEqual(rates['detector_cps'], total, delta=.01)
            self.assertAlmostEqual(rates['transmitted_signal_cps'], total-50, delta=.01)
            twin = beta.expected_rates(dict(settings, foil_spec_um=50, foil_count=count*2))
            if count*2 <= 24:
                self.assertEqual(twin, rates)
        empty = beta.expected_rates(dict(source_present=0, foil_spec_um=100, foil_count=24))
        self.assertEqual((empty['detector_cps'], empty['transmitted_signal_cps']), (50, 0))
        self.assertEqual(beta.CALIBRATED_AREAL_DENSITY_G_CM2, .4)
        self.assertGreater(beta.expected_rates(dict(source_present=1, foil_spec_um=100, foil_count=16))['areal_density_g_cm2'], .4)

    def test_previous_independent_whole_preserves_original_mean_and_observations(self):
        previous = previous_definition()
        source = Session(previous, seed=187)
        source.set('source_present', 1)
        source.set_output(beta.DETECTOR_OUTPUT, True)
        source.start_group(('counter', 'counter_b'))
        source.advance(3)
        source.stop_group(('counter', 'counter_b'))
        for device in ('counter', 'counter_b'):
            source.snapshot(device)
        document = capture_session(source)
        original = deepcopy(document)
        restored = reopen_session(load_package(package_bytes(document)), beta.EXPERIMENT)
        self.assertEqual([s.counts for s in restored.snapshots], [(284,), (290,)])
        self.assertIn('历史响应', restored.experiment.title)
        self.assertEqual(restored.experiment.particle_flow({'source_present': 0, 'foil_count': 0})['background_rate_s'], 2)
        self.assertEqual(restored.experiment.model({'source_present': 1, 'foil_count': 0}, 0, 1, Random(187)),
                         {'beta_detector': (97,), 'beta_detector_b': (105,)})
        restored.set_output(beta.DETECTOR_OUTPUT, True)
        restored.start_group(('counter', 'counter_b'))
        restored.advance(1)
        for device in ('counter', 'counter_b'):
            restored.snapshot(device)
        again = reopen_session(load_package(package_bytes(capture_session(restored, document))), beta.EXPERIMENT)
        self.assertIn('历史响应', again.experiment.title)
        self.assertEqual(document, original)

    def test_previous_single_items_keep_fixed_prefix_and_add_current_response(self):
        old = Session(previous_definition(), seed=187)
        old.set('source_present', 1)
        old.set_output(beta.DETECTOR_OUTPUT, True)
        old.start_group(('counter', 'counter_b'))
        old.advance(3)
        for device in ('counter', 'counter_b'):
            old.snapshot(device)
        document = capture_session(old)
        for format in ('json', 'csv'):
            target, fresh = Session(beta.EXPERIMENT, seed=187), Session(beta.EXPERIMENT, seed=187)
            for session in (target, fresh):
                session.set('source_present', 1)
                session.set_output(beta.DETECTOR_OUTPUT, True)
            for item in document['items']:
                device = item['document']['snapshot']['device']
                saved = decode_measurement(export_item(document, item['id'], format), beta.EXPERIMENT, device)
                target.load_measurement(device, saved.snapshot)
            for session in (target, fresh):
                session.start_group(('counter', 'counter_b'))
                session.advance(1)
            for device, prefix in (('counter', 284), ('counter_b', 290)):
                self.assertEqual(target.instrument(device).counts[0]-prefix, fresh.instrument(device).counts[0])
                self.assertEqual(target.instrument(device).exposure_s, 4)
                snapshot = target.snapshot(device)
                self.assertIsNotNone(snapshot.segments[0].origin)
                self.assertIsNone(snapshot.segments[-1].origin)
            self.assertIs(target.experiment, beta.EXPERIMENT)

    def test_unknown_previous_response_or_binding_is_not_accepted(self):
        info = describe(previous_definition())
        info['outputs'][1]['response'] += ' different response'
        self.assertIs(beta.restore_definition(info), NotImplemented)
        info = describe(previous_definition())
        info['devices'][1]['input'] = beta.DETECTOR_OUTPUT
        self.assertIs(beta.restore_definition(info), NotImplemented)


if __name__ == '__main__':
    unittest.main()
