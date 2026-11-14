"""Run the same operations through the workbench controller and the CLI."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from nuclemu.workbench import Workbench


ROOT = Path(__file__).resolve().parents[1]


class EntryPointParityTests(unittest.TestCase):
    def test_exports_match_for_identical_operations_at_different_refresh_rates(self):
        scenarios = (
            ("alpha", "mca", "alpha_detector", 187,
             [(2.25, {"source_present": 1, "foil_spec_um": 1, "foil_count": 0}),
              (1.25, {"foil_spec_um": 1, "foil_count": 5})], [172, 86]),
            ("beta", "counter", "beta_detector", 42,
             [(1.25, {"source_present": 0, "foil_spec_um": 100}),
              (2.5, {"source_present": 1, "foil_count": 4})], [61, 3774]),
        )
        for experiment, device, output, seed, steps, expected_counts in scenarios:
            with self.subTest(experiment=experiment), TemporaryDirectory() as directory:
                cli_path = Path(directory, "cli.json")
                command = [sys.executable, "-m", "nuclemu", "run", experiment,
                           "--seed", str(seed), "--device", device,
                           "--enable-output", output, "--output", str(cli_path)]
                for duration, settings in steps:
                    fields = [str(duration), *(f"{k}={v}" for k, v in settings.items())]
                    command.extend(["--step", ",".join(fields)])
                subprocess.run(command, check=True, capture_output=True, cwd=ROOT,
                               text=True, encoding="utf-8")
                reference = json.loads(cli_path.read_text(encoding="utf-8"))
                self.assertEqual(list(reference["devices"]), [device])
                observed_counts = [sum(s["readings"][device]) for s in reference["segments"]]
                self.assertEqual(observed_counts, expected_counts)
                self.assertTrue(all(count > 0 for count in observed_counts))
                self.assertEqual([s["acquisition"] for s in reference["segments"]], [1, 2])
                self.assertEqual([s["end_s"] - s["start_s"] for s in reference["segments"]],
                                 [duration for duration, _ in steps])

                # The CLI advances each entire timed step. The controller below
                # follows the same physical operations with different UI ticks.
                for speed, physical_tick in ((1, .25), (2, .125), (8, .05)):
                    with self.subTest(speed=speed, physical_tick=physical_tick):
                        workbench = Workbench(seed=seed)
                        workbench.switch(experiment)
                        workbench.bind_device(device)
                        workbench.set_output(output, True)
                        workbench.set_speed(speed)
                        for index, (duration, settings) in enumerate(steps):
                            if index:
                                workbench.clear(device=device)
                            workbench.configure(settings)
                            workbench.start(duration, device=device)
                            for _ in range(round(duration / physical_tick)):
                                workbench.advance(physical_tick / speed)
                                workbench.product()
                            state = workbench.session.instrument(device)
                            self.assertFalse(state.running)
                            self.assertEqual(state.exposure_s, duration)
                            self.assertEqual(state.acquisition, index + 1)
                        workbench_path = Path(directory, f"workbench-{speed}.json")
                        workbench.export(workbench_path, all_segments=True)
                        actual = json.loads(workbench_path.read_text(encoding="utf-8"))
                        self.assertEqual(actual, reference)
