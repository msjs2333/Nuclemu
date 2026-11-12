"""Independent repeats retain Poisson statistics and strict historical modes."""

from copy import deepcopy
from random import Random
from statistics import mean, variance, correlation
import unittest

from examples.beta_window_rows import acquire, rows
from nuclemu.catalog import describe
from nuclemu.core import Session
from nuclemu.exchange import capture_session, reopen_session
from nuclemu.experiments import beta


def shared_info():
    info = describe(beta.EXPERIMENT)
    info['outputs'] = info['outputs'][:1]
    info['outputs'][0]['response'] = beta.LEGACY_SHARED_RESPONSE
    for device in info['devices']:
        device['input'] = beta.DETECTOR_OUTPUT
    return info


class IndependentBetaTests(unittest.TestCase):
    def test_both_routes_have_the_same_poisson_mean_variance_and_small_correlation(self):
        for source, foil in ((0, 0), (1, 0), (1, 4), (1, 24)):
            with self.subTest(source=source, foil=foil):
                settings = dict(source_present=source, foil_count=foil, foil_spec_um=100)
                rng = Random(187)
                samples = [beta.sample_counts(settings, i, i+1, rng) for i in range(5000)]
                a = [s[beta.DETECTOR_OUTPUT][0] for s in samples]
                b = [s[beta.DETECTOR_OUTPUT_B][0] for s in samples]
                expected = beta.expected_rates(settings)['detector_cps']
                for values in (a, b):
                    self.assertLess(abs(mean(values)-expected), 5*(expected/len(values))**.5)
                    self.assertLess(abs(variance(values)-expected), .09*expected)
                self.assertLess(abs(correlation(a, b)), .06)
                # Equality can occur by chance; it is not forbidden per pair.
                self.assertTrue(any(x == y for x, y in zip(a, b)))

    def test_seed_operations_and_single_switch_apply_to_both_routes(self):
        self.assertEqual(rows(acquire(seed=187)), rows(acquire(seed=187)))
        s = Session(beta.EXPERIMENT, seed=187)
        s.set_output(beta.DETECTOR_OUTPUT, True)
        self.assertEqual(dict(s.output_enabled), {beta.DETECTOR_OUTPUT: True, beta.DETECTOR_OUTPUT_B: True})
        s.start_group(('counter', 'counter_b'))
        s.advance(2)
        s.set_output(beta.DETECTOR_OUTPUT_B, False)
        s.advance(1)
        for device in ('counter', 'counter_b'):
            self.assertEqual(s.instrument(device).exposure_s, 3)
            self.assertEqual(s.instrument_windows(device)[-1].counts, (0,))

    def test_historical_selector_does_not_accept_unknown_physical_response(self):
        info = shared_info()
        old = beta.restore_definition(info)
        self.assertIsNone(old.restore_definition)
        self.assertEqual(len(old.outputs), 1)
        for key, value in (('response', 'Different physical response'), ('channels', 2), ('unit', 'keV')):
            bad = deepcopy(info)
            bad['outputs'][0][key] = value
            self.assertIs(beta.restore_definition(bad), beta.EXPERIMENT)
            s = Session(old, seed=187)
            doc = capture_session(s)
            doc['definition'] = bad
            with self.assertRaises(ValueError):
                reopen_session(doc, beta.EXPERIMENT)

    def test_historical_single_window_without_foil_spec_uses_original_thickness(self):
        info = shared_info()
        info['devices'] = info['devices'][:1]
        info['parameters'] = [p for p in info['parameters'] if p['key'] != 'foil_spec_um']
        old = beta.restore_definition(info)
        self.assertIsNot(old, beta.EXPERIMENT)
        self.assertEqual([d.id for d in old.devices], ['counter'])
        settings = dict(source_present=1, foil_count=4)
        self.assertEqual(beta.expected_rates(settings), beta.expected_rates(dict(settings, foil_spec_um=100)))
        s = Session(old)
        s.set_output(beta.DETECTOR_OUTPUT, True)
        s.start(1)
        s.advance(1)
        restored = reopen_session(capture_session(s), beta.EXPERIMENT)
        self.assertEqual(len(restored.experiment.devices), 1)


if __name__ == '__main__':
    unittest.main()
