"""One physical detector switch can control several declared signal outputs."""

from dataclasses import replace
import unittest

from nuclemu.core import Component, Device, Experiment, Session, SignalOutput


def definition():
    return Experiment('grouped-outputs', 'Grouped outputs', '', (),
        tuple(Device(key, 'counter', key, input=output)
              for key, output in (('a', 'left'), ('b', 'right'), ('c', 'other'))),
        lambda settings, start, end, rng: {
            key: (round(rate * (end - start)),)
            for key, rate in (('left', 4), ('right', 8), ('other', 12))},
        outputs=tuple(SignalOutput(key, key) for key in ('left', 'right', 'other')),
        components=(Component('detector', 'detector', 'Detector', output='left',
                              outputs=('left', 'right')),
                    Component('other-detector', 'detector', 'Other detector', output='other'),
                    Component('counter', 'instrument', 'Counter', device='a', devices=('a', 'b', 'c'))))


class OutputGroupTests(unittest.TestCase):
    def test_one_switch_settles_the_old_interval_once_and_preserves_other_output(self):
        session = Session(definition())
        session.start_group(('a', 'b', 'c'))
        session.set_output('left', True)
        session.set_output('other', True)
        session.advance(.25)
        session.set_output('right', False)
        self.assertEqual(dict(session.output_enabled), dict(left=False, right=False, other=True))
        session.advance(.75)
        session.stop_group(('a', 'b', 'c'))
        self.assertEqual([session.instrument(key).counts for key in ('a', 'b', 'c')],
                         [(1,), (2,), (12,)])
        self.assertEqual([session.instrument(key).exposure_s for key in ('a', 'b', 'c')], [1] * 3)
        changes = [row for row in session.configuration_history if row.kind == 'output']
        self.assertEqual([dict(row.values) for row in changes],
                         [dict(left=True, right=True), dict(other=True), dict(left=False, right=False)])
        for info in session.rounds:
            self.assertEqual([dict(change.values) for change in info.output_changes],
                             [dict(left=True, right=True), dict(other=True), dict(left=False, right=False)])

    def test_invalid_switch_and_equivalent_group_switch_do_not_sample(self):
        session = Session(definition())
        session.set_output('left', True)
        session.start_group(('a', 'b'))
        session.advance(.25)
        before = (session.time_s, session.records, session._rng.getstate(), session.configuration_history)
        session.set_output('right', True)
        for output, value in (('missing', True), ('left', 1)):
            with self.assertRaises(ValueError):
                session.set_output(output, value)
        self.assertEqual((session.time_s, session.records, session._rng.getstate(), session.configuration_history), before)

    def test_groups_require_unique_known_members_and_an_explicit_primary_switch(self):
        course = definition()
        for members, primary in ((('left', 'left'), 'left'), (('left', 'missing'), 'left'),
                                 (('right',), 'left'), (('left', 'right'), None)):
            with self.subTest(members=members, primary=primary), self.assertRaises(ValueError):
                replace(course, components=(replace(course.components[0], output=primary, outputs=members),
                                            *course.components[1:]))
        with self.assertRaises(ValueError):
            replace(course, components=(*course.components,
                Component('duplicate', 'detector', 'Duplicate', output='right', outputs=('right', 'other'))))


if __name__ == '__main__':
    unittest.main()
