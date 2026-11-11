"""Local measurement archives. Each transaction publishes a complete set of changes."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3


class ArchiveStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.directory / "workbench.sqlite3")
        db.execute("""CREATE TABLE IF NOT EXISTS archives (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
            time_s REAL NOT NULL, metadata TEXT NOT NULL, updated TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS segments (
            archive TEXT NOT NULL, idx INTEGER NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (archive, idx))""")
        return db

    @staticmethod
    def _remove(db, identifier):
        db.execute("DELETE FROM segments WHERE archive=?", (identifier,))
        db.execute("DELETE FROM archives WHERE id=?", (identifier,))

    def remove(self, identifier):
        with closing(self._connect()) as db, db:
            self._remove(db, identifier)

    def list(self):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, kind, title, time_s, updated FROM archives ORDER BY updated DESC, rowid DESC")
            return [dict(id=i, kind=k, title=t, time_s=s, updated=u) for i, k, t, s, u in rows]

    def read(self, identifier):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            entry = db.execute("SELECT metadata FROM archives WHERE id=?", (identifier,)).fetchone()
            if entry is None:
                raise ValueError("没有找到该实验记录。")
            doc = json.loads(entry[0])
            rows = db.execute("SELECT data FROM segments WHERE archive=? ORDER BY idx", (identifier,))
            doc["product"]["segments"] = [json.loads(row[0]) for row in rows]
            return doc

    def write(self, identifier, kind, doc, *, start=0, remove=None):
        product = dict(doc["product"])
        segments = product.pop("segments")
        header = json.dumps(dict(doc, product=product), ensure_ascii=False, allow_nan=False)
        with closing(self._connect()) as db, db:
            db.execute("""INSERT OR REPLACE INTO archives VALUES(?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
                       (identifier, kind, doc["definition"]["title"], doc["time_s"], header))
            db.executemany("INSERT OR REPLACE INTO segments VALUES(?,?,?)", (
                (identifier, i, json.dumps(segments[i], separators=(",", ":"), allow_nan=False))
                for i in range(start, len(segments))))
            db.execute("DELETE FROM segments WHERE archive=? AND idx>=?", (identifier, len(segments)))
            if remove and remove != identifier:
                self._remove(db, remove)
