"""SQLite transaction couples the mock side effect and its durable receipt."""

import hashlib
import sqlite3
from contextlib import contextmanager
from uuid import uuid4

from .models import Resolution


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                case_id TEXT UNIQUE NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (
                operation TEXT PRIMARY KEY, receipt TEXT NOT NULL, amount INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def existing(self, key, request):
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT fingerprint,result FROM cases WHERE key=?", (key,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise Conflict("Idempotency key belongs to another request")
            return Resolution.model_validate_json(row[1])
        return None

    def get(self, case_id):
        with self.connect() as db:
            row = db.execute("SELECT result FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            raise KeyError("case not found")
        return Resolution.model_validate_json(row[0])

    @staticmethod
    def execute(db, result):
        # Semantic key stops the same order/action repeating through different request keys.
        operation = f"{result.order_id}:{result.proposal.action}:v1"
        db.execute(
            "INSERT OR IGNORE INTO actions VALUES (?,?,?)",
            (operation, str(uuid4()), result.amount_cents),
        )
        row = db.execute(
            "SELECT receipt,amount FROM actions WHERE operation=?", (operation,)
        ).fetchone()
        if row[1] != result.amount_cents:
            raise Conflict("Existing action has a different amount")
        return result.model_copy(update={"receipt": row[0], "status": "completed"})

    def finish_new(self, key, request, result):
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if result.status == "completed":
                result = self.execute(db, result)
            db.execute(
                "INSERT INTO cases VALUES (?,?,?,?)",
                (key, fingerprint, result.case_id, result.model_dump_json()),
            )
        return result

    def review(self, case_id, approve):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if not row:
                raise KeyError("case not found")
            result = Resolution.model_validate_json(row[0])
            if result.status in ("completed", "rejected"):
                if (result.status == "completed") != approve:
                    raise Conflict("Case already finalized with a different decision")
                return result
            if result.status != "awaiting_approval":
                raise Conflict("Case is not awaiting approval")
            result = (
                self.execute(db, result)
                if approve
                else result.model_copy(update={"status": "rejected"})
            )
            db.execute(
                "UPDATE cases SET result=? WHERE case_id=?", (result.model_dump_json(), case_id)
            )
        return result
