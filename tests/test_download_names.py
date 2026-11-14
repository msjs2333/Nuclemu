"""Default download names follow local save time without changing saved identity."""

from copy import deepcopy
from base64 import b64encode
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from nuclemu.core import Session
from nuclemu.experiments.alpha import EXPERIMENT
from nuclemu.experiments.beta import EXPERIMENT as BETA
from nuclemu.exchange import (batch_download, cache_calibration, capture_session, load_item,
                              load_package, package_download, package_bytes, link_measurements)
from nuclemu.results import Calibration
from nuclemu.web_download import make_download
from nuclemu.web_session import Application
from nuclemu.download_names import download_prefix, measurement_label


class DownloadNameTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("nuclemu.download_names.datetime")
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.now.now.return_value = datetime(2026, 11, 12, 15, 4, 5, 123456)
        self.stamp = patch("nuclemu.download_names._last_time", None)
        self.stamp.start()
        self.addCleanup(self.stamp.stop)

    def document(self):
        session = Session(EXPERIMENT)
        session.configure({"source_present": 1})
        session.set_output("alpha_detector", True)
        session.start(1, device="mca")
        session.advance(1)
        session.snapshot("mca")
        doc = capture_session(session)
        calibration = cache_calibration(doc, Calibration("alpha", "mca", 1024, 0, 0, 1000, 6))
        return doc, doc["items"][0]["id"], calibration

    def test_package_and_single_formats_use_save_time_not_simulation_time(self):
        doc, measurement, calibration = self.document()
        original = deepcopy(doc)
        name, _, data = package_download(doc)
        self.assertRegex(name, r"^AEL_20261112-150405-\d{6}\.nuclemu$")
        self.assertEqual(load_package(data), original)
        names = {name}
        for identity, kind, fmt in ((measurement, "spectrum", "json"),
                (measurement, "spectrum", "csv"), (calibration, "calibration", "json")):
            name, _, data = batch_download(doc, [{"id": identity, "format": fmt}])
            self.assertRegex(name, rf"^AEL_20261112-150405-\d{{6}}_{kind}\.{fmt}$")
            self.assertNotIn(name, names)
            names.add(name)
            self.assertEqual(load_item(data)["items"][0]["id"], identity)
        self.assertEqual(doc, original)

    def test_batch_members_share_stamp_and_duplicate_selections_do_not_collide(self):
        doc, measurement, calibration = self.document()
        choices = [{"id": measurement, "format": "csv"}]*2 + [{"id": calibration, "format": "json"}]
        name, mime, data = batch_download(doc, choices)
        self.assertRegex(name, r"^AEL_20261112-150405-\d{6}_records\.zip$")
        self.assertEqual(mime, "application/zip")
        with ZipFile(BytesIO(data)) as archive:
            members = archive.namelist()
            self.assertEqual(len(set(members)), 3)
            self.assertTrue(all(n.startswith(name.removesuffix('_records.zip') + '_') for n in members))
            self.assertTrue(all("nuclemu" not in n for n in members))
            self.assertEqual([load_item(archive.read(n))["items"][0]["id"] for n in members],
                             [measurement, measurement, calibration])

    def test_single_spectrum_saved_through_instrument_group_keeps_spectrum_label(self):
        doc,measurement,_=self.document()
        link_measurements(doc,[measurement],members=['mca'])
        name,_,data=batch_download(doc,[dict(id=measurement,format='csv')])
        self.assertRegex(name,r'^AEL_\d{8}-\d{6}-\d{6}_spectrum\.csv$')
        self.assertEqual(load_item(data)['items'][0]['id'],measurement)

    def test_legacy_measurement_calibration_and_batch_names(self):
        lab = SimpleNamespace(info={"id": "beta", "short_code": "BABS"}, export=lambda item: b"unchanged")
        products = [dict(kind="measurement", device="counter_b", indices=[0], format="csv"),
                    dict(kind="measurement", device="counter", indices=[0, 1], format="json"),
                    dict(kind="calibration", device="mca", format="json")]
        for product, label in zip(products, ("measurement-counter_b-segment-1", "measurement-counter-segments", "calibration-mca")):
            name, _, data = make_download(lab, [product])
            self.assertRegex(name, rf"^BABS_20261112-150405-\d{{6}}_{label}\.{product['format']}$")
            self.assertEqual(data, b"unchanged")
        name, _, data = make_download(lab, [*products, products[0]])
        stamp = name.removesuffix("_records.zip")
        with ZipFile(BytesIO(data)) as archive:
            self.assertEqual(len(set(archive.namelist())), 4)
            self.assertTrue(all(n.startswith(stamp + "_") for n in archive.namelist()))

    def test_old_package_missing_code_downloads_with_current_catalogue_code(self):
        for experiment, code in ((EXPERIMENT, "AEL"), (BETA, "BABS")):
            with self.subTest(experiment=experiment.id), TemporaryDirectory() as folder:
                session = Session(experiment)
                session.start(1)
                session.advance(1)
                device = experiment.devices[-1].id
                session.snapshot(device)
                old = capture_session(session)
                del old["definition"]["short_code"]
                raw = package_bytes(old)
                original = deepcopy(old)
                app = Application({experiment.id: experiment}, folder, clock=lambda: 0)
                state = app.request("/api/open_package", {"file": b64encode(raw).decode()})
                name, _, data = app.request("/api/download", {"session": state["id"], "scope": "experiment"})
                self.assertTrue(name.startswith(code + "_"))
                self.assertEqual(load_package(data)["items"], old["items"])
                self.assertEqual(old, original)
                name, _, _ = app.request("/api/download", {"session": state["id"],
                    "snapshots": [{"id": old["items"][0]["id"], "format": "csv"}]})
                self.assertIn("spectrum" if experiment.id == "alpha" else "counts-B", name)

    def test_unknown_external_course_and_multiple_devices_have_safe_distinct_names(self):
        definition = dict(id="External: /Lab?", devices=[
            dict(id="left/path", kind="spectrum"), dict(id="right:path", kind="spectrum")])
        prefix = download_prefix(definition)
        self.assertRegex(prefix, r"^[A-Za-z0-9][A-Za-z0-9_-]*_20261112-150405-\d{6}$")
        labels = [measurement_label(definition, d["id"]) for d in definition["devices"]]
        self.assertEqual(labels, ["spectrum-left_path", "spectrum-right_path"])


if __name__ == "__main__":
    unittest.main()
