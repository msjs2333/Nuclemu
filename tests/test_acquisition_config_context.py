"""An unapplied draft cannot silently overwrite another page's settings."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover
from nuclemu.web_session import Application


class AcquisitionConfigContextTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 0
        self.app = Application(discover(), folder.name, lambda: self.now)

    def act(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def unchanged(self):
        lab = self.app.lab
        s = lab.work.session
        return s.time_s, s._rng.getstate(), s.records, tuple(s.instrument(d.id) for d in s.experiment.devices), deepcopy(lab.analysis)

    def test_old_single_draft_rejected_before_sampling_and_explicit_apply_can_replace(self):
        self.app.open({'experiment': 'alpha'})
        self.act('instrument_config', device='mca', duration_s=10, count_limit=None, window_s=1)
        expected = dict(duration_s=10, count_limit=None, window_s=1)
        self.act('instrument_config', device='mca', duration_s=20)
        self.act('output', output='alpha_detector', enabled=True)
        before = self.unchanged()
        self.now = 5
        with self.assertRaisesRegex(ValueError, '采集设置已改变'):
            self.act('instrument_config', device='mca', duration_s=30, expected=expected)
        self.assertEqual(self.unchanged(), before)
        self.act('instrument_config', device='mca', duration_s=30)
        self.assertEqual(self.app.lab.work.session.instrument('mca').duration_s, 30)

    def test_pending_window_compared_as_applied_next_value(self):
        self.app.open({'experiment': 'alpha'})
        self.act('instrument_config', device='mca', window_s=5)
        self.act('start', device='mca')
        self.now = 1
        self.act('instrument_config', device='mca', window_s=2)
        self.act('stop', device='mca', acquisition=1, cycle=1)
        self.act('instrument_config', device='mca', duration_s=10,
                 expected=dict(duration_s=None, count_limit=None, window_s=2))
        before = self.unchanged()
        with self.assertRaisesRegex(ValueError, '采集设置已改变'):
            self.act('instrument_config', device='mca', duration_s=20,
                     expected=dict(duration_s=10, count_limit=None, window_s=5))
        self.assertEqual(self.unchanged(), before)

    def test_group_checks_both_targets_and_accepts_window_changes_independently(self):
        self.app.open({'experiment': 'beta'})
        self.act('instrument_group_config', component='counter', duration_s=10, count_limit=None)
        self.app.lab.work.session.configure_acquisition('counter_b', duration_s=20)
        before = self.unchanged()
        with self.assertRaisesRegex(ValueError, '采集设置已改变'):
            self.act('instrument_group_config', component='counter', duration_s=30,
                     expected=dict(duration_s=10, count_limit=None))
        self.assertEqual(self.unchanged(), before)
        self.act('instrument_group_config', component='counter', duration_s=10)
        self.act('window_config', component='counter', device='counter_b', window_s=7)
        self.act('instrument_group_config', component='counter', duration_s=30,
                 expected=dict(duration_s=10, count_limit=None))
        self.assertEqual([self.app.lab.work.session.instrument(d).duration_s for d in ('counter', 'counter_b')], [30, 30])


if __name__ == '__main__':
    unittest.main()
