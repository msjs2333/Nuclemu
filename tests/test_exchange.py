"""Real portable-file round trips, independent of any Web database or renderer."""

from copy import deepcopy
from contextlib import closing
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from nuclemu.catalog import describe, discover
from nuclemu.core import Device, Experiment, Parameter, Session, SignalOutput
from nuclemu.exchange import (batch_download, bind_calibration, cache_calibration,
    capture_session, convert_archive, export_item, import_item, list_items, load_item,
    load_package, package_bytes, reopen_session, save_package, validate_document)
from nuclemu.results import Calibration
from nuclemu.web_store import ArchiveStore


def course():
    def model(settings, start, end, rng):
        return {"detector": (0, 0, round((end-start)*20), 0, 0, 0, 0, 0)}
    return Experiment("portable", "Portable lab", "Measured spectrum",
        (Parameter("foil_count", "Foils", "片", 0, 0, 40, integer=True),),
        (Device("mca", "spectrum", "MCA", 8, input="detector"),), model,
        outputs=(SignalOutput("detector", "Detector", 8),))


def saved(*, twice=False):
    s = Session(course(), seed=187)
    s.set_output("detector", True)
    s.start(5, device="mca")
    s.advance(2)
    s.configure({"foil_count": 5})
    s.advance(1)
    s.snapshot("mca")
    s.advance(2)
    if twice:
        s.snapshot("mca")
    return s


class ExchangeTests(unittest.TestCase):
    def test_three_second_snapshot_and_five_second_round_reopen_independently(self):
        s = saved()
        before = (s.instrument("mca"), list(s.records), s.time_s, s.snapshots)
        doc = capture_session(s)
        self.assertEqual(before, (s.instrument("mca"), list(s.records), s.time_s, s.snapshots))
        self.assertEqual(doc["rounds"][0]["exposure_s"], 5)
        measurement, = doc["items"]
        self.assertEqual(measurement["document"]["snapshot"]["exposure_s"], 3)
        self.assertEqual(sum(sum(row["readings"]["mca"]) for row in measurement["document"]["segments"]), 60)
        self.assertNotIn("counts", doc["rounds"][0])
        self.assertNotIn("counts", doc["instruments"]["mca"])
        self.assertEqual(doc["rounds"][0]["changes"][0]["exposure_s"], 2)
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            path = Path(first) / "experiment.nuclemu"
            save_package(path, doc)
            elsewhere = Path(second) / "copied.nuclemu"
            elsewhere.write_bytes(path.read_bytes())
            loaded = load_package(elsewhere)
            self.assertEqual(loaded, doc)
            with ZipFile(elsewhere) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual((manifest["format"], manifest["version"]), ("nuclemu.package/1", 1))
                with closing(sqlite3.connect(":memory:")) as db:
                    db.deserialize(archive.read("experiment.sqlite3"))
                    self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 1)
                    segments = [json.loads(row[0]) for row in db.execute("SELECT data FROM segments ORDER BY idx")]
                    self.assertEqual(max(s["end_s"] for s in segments), 3)
                    self.assertEqual(sum(sum(s["readings"]["mca"]) for s in segments), 60)
            reopened = reopen_session(loaded, course())
            self.assertFalse(reopened.running)
            self.assertFalse(reopened.clock_running)
            self.assertEqual(reopened.instrument("mca").counts, (0,)*8)
            self.assertEqual(reopened.instrument("mca").exposure_s, 0)
            reopened.set_output("detector", True)
            reopened.start(1, device="mca")
            reopened.advance(1)
            fresh = reopened.snapshot("mca")
            self.assertEqual((fresh.acquisition, fresh.exposure_s, sum(fresh.counts)), (2, 1, 20))
            continued = capture_session(reopened, loaded)
            self.assertEqual(continued["items"][0], measurement)
            self.assertEqual(len(continued["items"]), 2)

    def test_unsaved_round_has_only_configuration_and_exposure(self):
        s = saved()
        s.clear(device="mca")
        s.configure({"foil_count": 7})
        s.start(1, device="mca")
        s.advance(1)
        doc = load_package(package_bytes(capture_session(s)))
        self.assertEqual(len(doc["rounds"]), 2)
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(doc["rounds"][1]["exposure_s"], 1)
        self.assertEqual(doc["rounds"][1]["initial_settings"]["foil_count"], 7)
        self.assertNotIn("readings", doc["rounds"][1])
        self.assertNotIn("counts", doc["rounds"][1])
        self.assertEqual(doc["configuration"]["settings"], {"foil_count": 7})
        self.assertEqual(doc["configuration"]["history"][-1]["values"], {"foil_count": 7})

    def test_two_overlapping_snapshots_keep_identity_and_cutoff_on_single_exports(self):
        doc = capture_session(saved(twice=True))
        ids = [i["id"] for i in doc["items"]]
        self.assertEqual([i["document"]["snapshot"]["acquisition"] for i in doc["items"]], [1, 1])
        calibration = cache_calibration(doc, Calibration("portable", "mca", 8, 0, 0, 7, 7), title="Calibration")
        for identity in ids:
            bind_calibration(doc, identity, calibration)
        doc["analysis"] = {"mca": {"roi": [0, 7], "reference": ids[0], "selected": ids[1], "background": None}}
        restored = load_package(package_bytes(doc))
        self.assertEqual(restored["analysis"], doc["analysis"])
        for identity, exposure, total in zip(ids, (3, 5), (60, 100)):
            for format in ("json", "csv"):
                with self.subTest(exposure=exposure, format=format):
                    bundle = load_item(export_item(restored, identity, format))
                    item = bundle["items"][0]
                    self.assertEqual(item, doc["items"][ids.index(identity)])
                    self.assertEqual(item["document"]["snapshot"]["exposure_s"], exposure)
                    self.assertEqual(sum(sum(s["readings"]["mca"]) for s in item["document"]["segments"]), total)
                    self.assertEqual(Calibration.from_document(bundle["items"][1]["document"]).energy(2), 2)
        name, mime, content = batch_download(restored, [{"id": ids[0], "format": "csv"},
            {"id": ids[1], "format": "json"}, {"id": calibration, "format": "json"}])
        self.assertEqual(mime, "application/zip")
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(len(archive.namelist()), 3)
            self.assertTrue(all(load_item(archive.read(name))["items"] for name in archive.namelist()))

    def test_import_same_names_and_local_snapshot_ids_does_not_replace_target(self):
        left, right = capture_session(saved()), capture_session(saved())
        self.assertEqual(left["items"][0]["title"], right["items"][0]["title"])
        original = deepcopy(left)
        cal = cache_calibration(right, Calibration("portable", "mca", 8, 0, 0, 7, 7))
        bind_calibration(right, right["items"][0]["id"], cal)
        imported = import_item(left, right, right["items"][0]["id"])
        self.assertEqual(left["items"][0], original["items"][0])
        self.assertEqual(left["configuration"], original["configuration"])
        self.assertEqual(left["rounds"], original["rounds"])
        self.assertNotEqual(imported, right["items"][0]["id"])
        self.assertNotEqual(imported, original["items"][0]["id"])
        self.assertEqual(left["items"][1]["source"], right["items"][0]["source"])
        self.assertEqual(left["items"][1]["calibration_id"], left["items"][2]["id"])
        loaded = load_package(package_bytes(left))
        reopened = reopen_session(loaded, course())
        self.assertEqual(len(reopened.snapshots), 1)  # Imported references are not live local rounds.
        self.assertEqual(len(capture_session(reopened, loaded)["items"]), 3)

    def test_item_reimported_from_own_package_stays_a_reference(self):
        doc = capture_session(saved())
        original = doc["items"][0]["id"]
        copied = import_item(doc, doc, original)
        self.assertNotEqual(copied, original)
        loaded = load_package(package_bytes(doc))
        session = reopen_session(loaded, course())
        self.assertEqual(len(session.snapshots), 1)
        self.assertEqual(len(capture_session(session, loaded)["items"]), 2)

    def test_acquisition_targets_and_changed_limits_survive_reopening(self):
        session = Session(course())
        session.set_output("detector", True)
        session.start(1, device="mca")
        session.advance(1)
        session.configure_acquisition("mca", duration_s=3, count_limit=100)
        session.start(device="mca")
        session.advance(2)
        session.snapshot("mca")
        doc = load_package(package_bytes(capture_session(session)))
        self.assertEqual(doc["rounds"][0]["initial_duration_s"], 1)
        self.assertEqual(doc["rounds"][0]["target_changes"][-1]["duration_s"], 3)
        restored = reopen_session(doc, course())
        state = restored.instrument("mca")
        self.assertEqual((state.duration_s, state.count_limit, state.exposure_s, state.running), (3, 100, 0, False))
        self.assertEqual(restored.rounds[0].target_changes[-1].duration_s, 3)

    def test_opening_never_invokes_current_model_and_checks_its_device_binding(self):
        doc = capture_session(saved())
        def unavailable(*args):
            raise AssertionError("Opening must never regenerate saved measurements")
        current = replace(course(), model=unavailable)
        restored = reopen_session(load_package(package_bytes(doc)), current)
        self.assertEqual(sum(restored.snapshots[0].counts), 60)
        changed = deepcopy(doc)
        changed["definition"]["devices"][0]["kind"] = "other-spectrum"
        changed["items"][0]["document"]["devices"]["mca"]["kind"] = "other-spectrum"
        with self.assertRaisesRegex(ValueError, "binding"):
            reopen_session(load_package(package_bytes(changed)), current)

    def test_legacy_sqlite_transfer_preserves_raw_thickness_spectrum_and_calibration(self):
        old = Experiment("alpha", "Alpha archive", "Old measured spectrum",
            (Parameter("foil_um", "Total thickness", "µm", 0, 0, 40),),
            (Device("mca", "spectrum", "MCA", 1024),), lambda *args: {})
        values = [0]*1024
        values[500] = 172
        product = dict(format="nuclemu.measurement/1", experiment="alpha", seed=187,
            devices={"mca": {"kind": "spectrum", "channels": 1024}}, segments=[dict(
                acquisition=1, start_s=0, end_s=2.25, settings={"foil_um": 2.5}, readings={"mca": values})])
        calibration = Calibration("alpha", "mca", 1024, 0, 0, 1000, 6)
        fields = calibration.document()
        del fields["format"], fields["unit"]
        document = dict(definition=describe(old), time_s=2.25, settings={"foil_um": 2.5},
            device="mca", analysis={"mca": dict(roi=[0, 1023], selected=0, reference=None, background=None)},
            calibrations={"mca": fields}, product=product)
        with TemporaryDirectory() as temporary:
            store = ArchiveStore(temporary)
            store.write("old-alpha", "archive", document)
            database = Path(temporary) / "workbench.sqlite3"
            original_bytes = database.read_bytes()
            doc = convert_archive(database, "old-alpha")
            self.assertEqual(database.read_bytes(), original_bytes)
            self.assertEqual(doc["configuration"]["settings"], {"foil_um": 2.5})
            self.assertEqual(doc["legacy"]["document"]["product"], product)
            copied = load_package(package_bytes(doc))
            measured = next(i for i in copied["items"] if i["kind"] == "measurement")
            self.assertEqual(measured["document"]["segments"][0]["readings"]["mca"], values)
            self.assertEqual(measured["document"]["segments"][0]["settings"], {"foil_um": 2.5})
            cal = next(i for i in copied["items"] if i["id"] == measured["calibration_id"])
            self.assertEqual(Calibration.from_document(cal["document"]).energy(500), 3)
            with self.assertRaises(ValueError):
                reopen_session(copied, discover()["alpha"])

    def test_invalid_files_and_failed_save_do_not_replace_valid_measurements(self):
        original = capture_session(saved())
        for mutation in (lambda d: d["items"][0]["document"]["snapshot"].update(exposure_s=5),
                         lambda d: d["items"][0]["document"]["segments"][0]["readings"]["mca"].__setitem__(0, -1),
                         lambda d: d["rounds"][0].update(counts=[100]),
                         lambda d: d["items"][0]["document"].update(experiment="another-course"),
                         lambda d: d["items"][0]["document"]["devices"]["mca"].update(kind="counter")):
            bad = deepcopy(original)
            mutation(bad)
            with self.assertRaises(ValueError):
                package_bytes(bad)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "saved.sqlite3"
            save_package(path, original)
            before = path.read_bytes()
            bad = deepcopy(original)
            bad["configuration"]["time_s"] = float("nan")
            with self.assertRaises(ValueError):
                save_package(path, bad)
            self.assertEqual(path.read_bytes(), before)
            with patch("pathlib.Path.replace", side_effect=OSError("simulated write failure")):
                with self.assertRaises(OSError):
                    save_package(path, original)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(list(Path(temporary).glob("*.tmp")))
        with self.assertRaises(ValueError):
            load_package(b"not sqlite")

    def test_manifest_version_digest_and_identity_are_checked(self):
        doc = capture_session(saved())
        with ZipFile(BytesIO(package_bytes(doc))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            database = archive.read("experiment.sqlite3")
        for bad in (dict(manifest, version=2), dict(manifest, sha256="wrong"),
                    dict(manifest, experiment="another-course"),
                    {k: v for k, v in manifest.items() if k != "id"}, []):
            output = BytesIO()
            with ZipFile(output, "w") as archive:
                archive.writestr("manifest.json", json.dumps(bad))
                archive.writestr("experiment.sqlite3", database)
            with self.assertRaises(ValueError):
                load_package(output.getvalue())
        identity = doc["items"][0]["id"]
        csv_file = export_item(doc, identity, "csv")
        # Header metadata is intact; changing the row's experiment must still fail.
        edited = csv_file.replace(b"\r\nportable,", b"\r\nanother-course,", 1)
        self.assertNotEqual(edited, csv_file)
        with self.assertRaisesRegex(ValueError, "CSV experiment"):
            load_item(edited)
        with self.assertRaises(ValueError):
            load_item(b"null")


if __name__ == "__main__":
    unittest.main()
