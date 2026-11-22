"""Durable FIFO of dictated prompts. Only a confirmed delivery removes the text."""
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


class Dictations:
    def __init__(self, run):
        self.path = Path(run) / "dictations.sqlite3"

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS prompts
                           (id TEXT PRIMARY KEY, session TEXT, text TEXT, pending INTEGER)""")
                yield db
        finally:
            db.close()

    def add(self, session, text, pending=False):
        ident = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO prompts VALUES (?, ?, ?, ?)", (ident, session, text, pending))
        return ident

    def first(self, session):
        if not self.path.exists():
            return None
        with self.connect() as db:
            row = db.execute("SELECT id, text FROM prompts WHERE session=? AND pending=1 "
                             "ORDER BY rowid LIMIT 1", (session,)).fetchone()
            return dict(row) if row else None

    def ack(self, session, ident):
        with self.connect() as db:
            db.execute("DELETE FROM prompts WHERE session=? AND id=?", (session, ident))

    def take_legacy(self, session):
        if not self.path.exists():
            return []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT text FROM prompts WHERE session=? AND pending=1 ORDER BY rowid",
                              (session,)).fetchall()
            db.execute("UPDATE prompts SET pending=0 WHERE session=?", (session,))
            return [row["text"] for row in rows]

    def drafts(self):
        if not self.path.exists():
            return []
        with self.connect() as db:
            return db.execute("SELECT session, text FROM prompts ORDER BY rowid").fetchall()

    def clear(self):
        """Delete every stored dictation and return the removed rows."""
        if not self.path.exists():
            return []
        with self.connect() as db:
            rows = db.execute("SELECT session, text FROM prompts ORDER BY rowid").fetchall()
            db.execute("DELETE FROM prompts")
            return rows
