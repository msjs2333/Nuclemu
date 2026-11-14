"""Historical model selection remains explicit and course-owned."""

from dataclasses import replace
import unittest

from nuclemu.catalog import describe, resolve_saved_experiment
from nuclemu.core import Device, Experiment


class SavedExperimentTests(unittest.TestCase):
    def setUp(self):
        self.course = Experiment('course', 'Course', '', (),
                                 (Device('counter', 'counter', 'Counter'),),
                                 lambda settings, start, end, rng: {'counter': (0,)})

    def test_default_and_unrecognized_history_keep_the_current_definition(self):
        saved = describe(self.course)
        self.assertIs(resolve_saved_experiment(self.course, saved), self.course)
        current = replace(self.course, restore_definition=lambda info: current)
        self.assertIs(resolve_saved_experiment(current, saved), current)

    def test_trusted_course_can_select_a_complete_historical_model(self):
        old = replace(self.course, title='Historical course')
        current = replace(self.course, restore_definition=lambda info: old)
        self.assertIs(resolve_saved_experiment(current, describe(old)), old)
        self.assertNotIn('restore_definition', describe(current))

    def test_explicit_no_historical_match_keeps_the_registered_definition(self):
        current = replace(self.course, title='Current teaching course',
                          restore_definition=lambda info: NotImplemented)
        self.assertIs(resolve_saved_experiment(current, describe(current)), current)

    def test_wrong_experiment_or_invalid_callback_result_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_saved_experiment(self.course, {'id': 'other'})
        for value in (None, {}, replace(self.course, id='other')):
            current = replace(self.course, restore_definition=lambda info: value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_saved_experiment(current, describe(self.course))
        with self.assertRaises(ValueError):
            replace(self.course, restore_definition=True)


if __name__ == '__main__':
    unittest.main()
