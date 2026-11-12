"""Independent services must not replace each other's archives or recovery drafts."""

from copy import deepcopy
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.legacy_web_fixture import legacy_course
from nuclemu.web_session import Application


class ArchiveOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        definition = legacy_course("alpha")
        self.definitions = {definition.id: definition}
        self.services(Path(self.folder.name))

    def services(self, directory):
        self.now = 0
        self.a = Application(self.definitions, directory, clock=lambda: self.now)
        self.b = Application(self.definitions, directory, clock=lambda: self.now)
        self.a.open({"experiment": "legacy_alpha", "seed": 187})

    def act(self, app, action, **data):
        return app.request("/api/action", dict(session=app.lab.id, action=action, **data))

    def acquire(self):
        self.act(self.a, "start", duration=1)
        self.now += 1
        self.a.state()

    def finish(self, app, *, save):
        token = self.act(app, "freeze")["confirmation_id"]
        return self.act(app, "save" if save else "discard", confirmation_id=token,
                        **({"exit": True} if save else {}))

    def test_old_archive_analysis_is_saved_as_one_owned_copy_without_truncating_new_data(self):
        self.acquire()
        self.act(self.a, "save")
        original_id = self.a.lab.archive_id
        self.b.open({"archive": original_id})
        self.acquire()
        self.acquire()
        self.act(self.a, "save")
        original = deepcopy(self.a.store.read(original_id))
        self.assertEqual(len(original["product"]["segments"]), 3)
        self.act(self.b, "analysis", device="mca", roi=[850, 870])
        self.act(self.b, "save")
        copy_id = self.b.lab.archive_id
        self.assertNotEqual(copy_id, original_id)
        saved = self.b.store.read(copy_id)
        self.assertEqual(len(saved["product"]["segments"]), 1)
        self.assertEqual(saved["analysis"]["mca"]["roi"], [850, 870])
        self.assertEqual(self.a.store.read(original_id), original)
        self.assertFalse(self.b.lab.state()["dirty"])
        self.act(self.b, "analysis", device="mca", roi=[900, 920])
        self.act(self.b, "save")
        self.assertEqual(self.b.lab.archive_id, copy_id)
        archives = [row for row in self.b.store.list() if row["kind"] == "archive"]
        self.assertEqual(len(archives), 2)
        self.assertEqual(self.a.store.read(original_id), original)
        reader = Application(self.definitions, self.folder.name, clock=lambda: self.now)
        reopened = reader.open({"archive": copy_id})
        self.assertEqual(reopened["analysis"]["roi"], [900, 920])
        self.assertEqual(len(reopened["product"]["segments"]), 1)

    def test_readonly_draft_save_or_discard_never_removes_or_rewrites_owner_recovery(self):
        for save in (False, True):
            for advanced in (False, True):
                with self.subTest(save=save, advanced=advanced):
                    folder = Path(self.folder.name) / f"{save}-{advanced}"
                    self.services(folder)
                    self.acquire()
                    draft_id = self.a.lab.draft_id
                    self.b.open({"draft": draft_id})
                    if advanced:
                        self.acquire()
                        self.acquire()
                    expected = deepcopy(self.a.store.read(draft_id))
                    self.act(self.b, "analysis", device="mca", roi=[850, 870])
                    # Even an unchanged producer must retain its complete recovery point.
                    with patch.object(self.b.store, "remove", side_effect=AssertionError("Unowned draft deletion")):
                        self.finish(self.b, save=save)
                    self.a.state()  # No new window or analysis edit to trigger a rewrite.
                    self.assertEqual(self.a.store.read(draft_id), expected)
                    restarted = Application(self.definitions, folder, clock=lambda: self.now)
                    restored = restarted.open({"draft": draft_id})
                    self.assertEqual(restored["product"], expected["product"])
                    self.assertEqual(len(restored["product"]["segments"]), 3 if advanced else 1)
                    if save:
                        archives = [row for row in restarted.store.list() if row["kind"] == "archive"]
                        self.assertEqual(len(archives), 1)
                        copy = restarted.store.read(archives[0]["id"])
                        self.assertEqual(len(copy["product"]["segments"]), 1)
                        self.assertEqual(copy["analysis"]["mca"]["roi"], [850, 870])

    def test_recovered_orphan_draft_remains_available_and_owner_still_cleans_its_own_draft(self):
        self.acquire()
        draft_id = self.a.lab.draft_id
        original = deepcopy(self.a.store.read(draft_id))
        # A producer may have terminated; viewing alone never proves it is safe to delete.
        self.b.open({"draft": draft_id})
        self.finish(self.b, save=True)
        restarted = Application(self.definitions, self.folder.name, clock=lambda: self.now)
        restored = restarted.open({"draft": draft_id})
        self.assertEqual(restored["product"], original["product"])
        self.assertTrue(restored["readonly"])
        self.assertEqual(restored["recovered_s"], 1)
        self.finish(self.a, save=False)
        self.assertNotIn(draft_id, [row["id"] for row in self.a.store.list()])

    def test_failed_copy_save_keeps_analysis_for_retry_and_never_changes_source(self):
        self.acquire()
        self.act(self.a, "save")
        original_id = self.a.lab.archive_id
        original = deepcopy(self.a.store.read(original_id))
        self.b.open({"archive": original_id})
        self.act(self.b, "analysis", device="mca", roi=[850, 870])
        copy_id = self.b.lab.archive_id
        token = self.act(self.b, "freeze")["confirmation_id"]
        with patch.object(self.b.store, "write", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.Error):
                self.act(self.b, "save", exit=True, confirmation_id=token)
        self.assertTrue(self.b.lab.state()["dirty"])
        self.assertEqual(self.b.lab.confirmation_id, token)
        self.assertEqual(self.b.lab.analysis["mca"]["roi"], [850, 870])
        self.assertEqual(self.a.store.read(original_id), original)
        self.act(self.b, "save", exit=True, confirmation_id=token)
        self.assertEqual(self.b.store.read(copy_id)["analysis"]["mca"]["roi"], [850, 870])
        self.assertEqual(self.a.store.read(original_id), original)

    def test_legacy_archive_without_new_metadata_saves_a_copy_without_schema_migration(self):
        self.acquire()
        doc = deepcopy(self.a.lab.document())
        doc.pop("measurement_end_s")
        for key in ("components", "connections", "guide", "question", "course"):
            doc["definition"].pop(key, None)
        for parameter in doc["definition"]["parameters"]:
            parameter.pop("options", None)
        for device in doc["definition"]["devices"]:
            device.pop("background_conditions", None)
        self.a.store.write("legacy", "archive", doc)
        original = deepcopy(self.a.store.read("legacy"))
        self.b.open({"archive": "legacy"})
        self.act(self.b, "analysis", device="mca", roi=[850, 870])
        self.act(self.b, "save")
        self.assertEqual(self.a.store.read("legacy"), original)
        self.assertEqual(self.b.store.read(self.b.lab.archive_id)["analysis"]["mca"]["roi"], [850, 870])
        with closing(self.b.store._connect()) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
