"""Run the same operations through the workbench controller and the CLI."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from nuclemu.gui import Workbench


class EntryPointParityTests(unittest.TestCase):
    def test_exports_match_for_identical_operations_at_different_refresh_rates(self):
        scenarios = (
            ("alpha", 187, [(2.25, {}), (1.25, {"foil_um": 5})]),
            ("beta", 42, [(1.25, {"source_present": 0}),
                          (2.5, {"source_present": 1, "foil_count": 4})]),
        )
        for experiment, seed, steps in scenarios:
            with self.subTest(experiment=experiment), TemporaryDirectory() as directory:
                gui_path = Path(directory, "gui.json")
                cli_path = Path(directory, "cli.json")
                workbench = Workbench(seed=seed)
                workbench.switch(experiment)
                workbench.set_speed(2)
                command = [sys.executable, "-m", "nuclemu", "run", experiment,
                           "--seed", str(seed), "--output", str(cli_path)]
                for duration, settings in steps:
                    fields = [str(duration), *(f"{k}={v}" for k, v in settings.items())]
                    command.extend(["--step", ",".join(fields)])
                    workbench.configure(settings)
                    workbench.start(duration)
                    for _ in range(round(duration / 0.25)):
                        workbench.advance(0.125)
                        workbench.product()
                    self.assertFalse(workbench.session.running)
                workbench.export(gui_path, all_segments=True)
                subprocess.run(command, check=True, capture_output=True)
                self.assertEqual(json.loads(gui_path.read_text(encoding="utf-8")),
                                 json.loads(cli_path.read_text(encoding="utf-8")))
