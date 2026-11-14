"""Long real instrument windows retain counts and conditions through CSV files."""

import csv
from io import StringIO
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest

from nuclemu.core import Session
from nuclemu.experiments.alpha import EXPERIMENT as ALPHA
from nuclemu.experiments.beta import EXPERIMENT as BETA
from nuclemu.exchange import (capture_session, decode_measurement, load_item, load_package,
                             package_bytes, reopen_session, save_item)


class LongCsvTests(unittest.TestCase):
    def test_real_long_windows_reopen_from_csv_with_changed_conditions(self):
        previous_limit = csv.field_size_limit()
        self.addCleanup(csv.field_size_limit, previous_limit)
        for experiment, duration, seed, foil_count in ((ALPHA, 120, 187, 2), (BETA, 1800, 42, 4)):
            with self.subTest(experiment=experiment.id), TemporaryDirectory() as folder:
                # Exercise the standard-library default even after another test
                # has imported a large CSV in this same Python process.
                csv.field_size_limit(131072)
                session = Session(experiment, seed=seed)
                device = experiment.devices[0]
                session.configure({"source_present": 1})
                session.set_output(experiment.outputs[0].id, True)
                session.start(duration, device=device.id, window_s=duration)
                session.advance(duration/2)
                session.configure({"foil_count": foil_count})
                session.advance(duration/2)
                saved = session.snapshot(device.id)
                document = capture_session(session)
                item = document["items"][0]
                path = Path(folder) / "source.csv"
                save_item(path, document, item["id"])
                original_bytes = path.read_bytes()
                # Parts were and remain stored in one cell. Both real cases
                # exceed 128 KiB without losing the actual condition changes.
                body = original_bytes.decode().split("\n", 1)[1]
                self.assertGreater(len(json.dumps(item["document"]["windows"][0]["parts"])), 131072)
                destination = Path(folder) / "offline"
                destination.mkdir()
                copied = destination / "measurement.csv"
                copyfile(path, copied)
                loaded = load_item(copied)
                self.assertEqual(loaded["items"][0], item)
                self.assertEqual(path.read_bytes(), original_bytes)
                self.assertEqual(len(list(csv.DictReader(StringIO(body)))), device.channels)
                decoded = decode_measurement(copied, experiment, device.id)
                self.assertEqual(decoded.snapshot.counts, saved.counts)
                self.assertEqual(decoded.snapshot.exposure_s, duration)
                self.assertEqual(decoded.snapshot.windows, saved.windows)
                self.assertEqual(decoded.snapshot.segments, saved.segments)
                conditions = decoded.snapshot.windows[0].parts
                self.assertEqual(conditions[0].settings["foil_count"], 0)
                self.assertEqual(conditions[-1].settings["foil_count"], foil_count)
                self.assertGreater(sum(decoded.snapshot.counts), 0)
                # A real load at this new session's t=0 must remain serializable.
                target = Session(experiment)
                target.load_measurement(device.id, decoded.snapshot)
                target.snapshot(device.id)
                reopened = reopen_session(load_package(package_bytes(capture_session(target))), experiment)
                self.assertEqual(reopened.snapshots[0].counts, saved.counts)
                self.assertEqual(reopened.snapshots[0].exposure_s, duration)


if __name__ == "__main__":
    unittest.main()
