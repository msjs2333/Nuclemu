"""Web exchange adapter uses only explicit instrument snapshots."""

from io import BytesIO
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

from nuclemu.core import Device, Experiment, SignalOutput
from nuclemu.exchange import load_item
from nuclemu.web_exchange import WebExchange
from nuclemu.workbench import Workbench


class WebExchangeTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock(side_effect=lambda settings, start, end, rng: {
            "detector": (int((end - start) * 10),)})
        self.course = Experiment("web-test", "Web test", "", (),
            (Device("counter", "counter", "Counter", input="detector"),),
            self.model, outputs=(SignalOutput("detector", "Detector"),))
        self.work = Workbench(definitions={self.course.id: self.course}, seed=42)
        self.work.set_output("detector", True)
        self.work.start(10, device="counter")
        self.exchange = WebExchange()

    def refresh(self, analysis=None):
        return self.exchange.refresh(self.work.session, device="counter",
                                     product=self.work.product(), analysis=analysis)

    def test_package_and_selected_download_use_saved_cutoffs_and_stable_ids(self):
        self.work.advance(3)
        first = self.work.snapshot(device="counter")
        before = self.refresh({"counter": {"selected": 0, "reference": 0, "background": None}})
        first_id = before["items"][0]["id"]
        self.assertEqual(before["analysis"]["counter"]["reference"], first_id)
        self.work.advance(2)
        second = self.work.snapshot(device="counter")
        saved = self.refresh({"counter": {"selected": 0, "reference": None, "background": None}})
        self.assertEqual(saved["items"][0]["id"], first_id)
        self.assertEqual(saved["analysis"]["counter"]["selected"], saved["items"][1]["id"])
        self.assertEqual([i["document"]["snapshot"]["exposure_s"] for i in saved["items"]], [3, 5])
        self.assertEqual((first.acquisition, second.acquisition), (1, 1))
        self.assertEqual((first.counts, second.counts), ((30,), (50,)))
        self.work.advance(2)
        unsaved = self.refresh({"counter": {"selected": 0, "reference": 0, "background": None}})
        self.assertEqual(len(unsaved["items"]), 2)
        self.assertIsNone(unsaved["analysis"]["counter"]["reference"])
        self.assertEqual(unsaved["analysis"]["counter"]["unresolved"], {"selected": 0, "reference": 0})
        name, mime, data = self.exchange.download_selected([{"id": first.id, "format": "json"}])
        self.assertTrue(name.endswith(".json"))
        self.assertEqual(mime, "application/json")
        selected = load_item(data)
        self.assertEqual([i["id"] for i in selected["items"]], [first_id])
        self.assertEqual(selected["items"][0]["document"]["snapshot"]["exposure_s"], 3)
        self.assertEqual(self.exchange.download_selected([{"id": first_id, "format": "json"}])[2], data)
        with self.assertRaises(ValueError):
            self.exchange.download_selected([{"id": 999, "format": "json"}])
        filename, mime, archive_bytes = self.exchange.download_package()
        self.assertTrue(filename.endswith(".nuclemu"))
        self.assertEqual(mime, "application/zip")
        with TemporaryDirectory() as folder:
            path = Path(folder) / filename
            path.write_bytes(archive_bytes)
            with ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {"manifest.json", "experiment.sqlite3"})
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["format"], "nuclemu.package/1")
                with closing(sqlite3.connect(":memory:")) as db:
                    db.deserialize(archive.read("experiment.sqlite3"))
                    self.assertEqual(db.execute("select count(*) from items").fetchone()[0], 2)
                    rows = [json.loads(row[0]) for row in db.execute("select data from segments")]
                    self.assertEqual(sorted(s["end_s"] for s in rows), [3, 5])
                    self.assertEqual(sorted(s["readings"]["counter"][0] for s in rows), [30, 50])
            self.model.reset_mock()
            reopened_adapter, reopened = WebExchange.load(path, self.course)
            self.model.assert_not_called()
            self.assertFalse(reopened.running)
            self.assertEqual([s.counts for s in reopened.snapshots], [(30,), (50,)])
            self.assertEqual([i["id"] for i in reopened_adapter.document["items"]],
                             [i["id"] for i in saved["items"]])
            refreshed = reopened_adapter.refresh(reopened, device="counter")
            self.assertEqual([i["id"] for i in refreshed["items"]], [i["id"] for i in saved["items"]])
            self.model.assert_not_called()

    def test_analysis_does_not_guess_from_equal_counts_or_other_instrument(self):
        self.work.advance(3)
        self.work.snapshot(device="counter")
        product = self.work.product()
        product["segments"][0]["readings"]["counter"][0] += 1
        doc = self.exchange.refresh(self.work.session, product=product,
            analysis={"counter": {"reference": 0, "selected": None, "background": None}})
        self.assertIsNone(doc["analysis"]["counter"]["reference"])
        self.assertEqual(doc["analysis"]["counter"]["unresolved"], {"reference": 0})


if __name__ == "__main__":
    unittest.main()
