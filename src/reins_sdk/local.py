"""Local, transactional Reins budget ledger shared with the macOS application.

Only task metadata, usage and costs are stored. Prompts, results and credentials
never enter this ledger. Costs are integer micro-dollars to avoid float races.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .client import AdmissionDenied, Charge

DEFAULT_LEDGER = Path.home() / "Library/Application Support/ReinsMac/sdk-ledger.sqlite3"
_UNIT = Decimal("1000000")


def _micros(value: str | Decimal, *, positive: bool = False) -> int:
    try:
        amount = Decimal(str(value)) * _UNIT
    except InvalidOperation as exc:
        raise ValueError("Cost must be a USD decimal") from exc
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ValueError("Cost must have at most six decimal places")
    result = int(amount)
    if result < 0 or (positive and result == 0) or result > 9_000_000_000_000_000:
        raise ValueError("Cost is outside the supported range")
    return result


def _usd(micros: int) -> str:
    return str((Decimal(micros) / _UNIT).quantize(Decimal("0.000001")))


class LocalReinsClient:
    """Budget and measure existing Python Agent calls on the same Mac as Reins.

    Each paid operation requires a conservative upper bound. Admission is atomic
    across local processes. Unknown charges remain reserved until reconciled.
    This controls only operations explicitly wrapped by the application.
    """

    def __init__(self, db_path: str | Path = DEFAULT_LEDGER):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.db_path.exists():
            fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, case_id TEXT, variant TEXT,
                    workflow TEXT NOT NULL, budget_micros INTEGER NOT NULL,
                    wrapup_micros INTEGER NOT NULL, max_operations INTEGER,
                    status TEXT NOT NULL, accepted INTEGER,
                    created REAL NOT NULL, finished REAL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    operation_key TEXT, phase TEXT NOT NULL, model TEXT NOT NULL,
                    reserved_micros INTEGER NOT NULL, actual_micros INTEGER,
                    status TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0, success INTEGER,
                    created REAL NOT NULL, settled REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS operation_once
                    ON operations(task_id, operation_key) WHERE operation_key IS NOT NULL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    kind TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL
                );
                PRAGMA user_version=1;
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def start_task(
        self, *, workflow: str, budget: str | Decimal,
        task_id: str | None = None, wrapup_reserve: str | Decimal = "0",
        max_operations: int | None = None, case_id: str | None = None,
        variant: str | None = None,
    ) -> str:
        if not workflow.strip() or (case_id is None) != (variant is None):
            raise ValueError("Provide workflow and both case_id/variant or neither")
        if max_operations is not None and max_operations < 1:
            raise ValueError("max_operations must be positive")
        limit, wrapup = _micros(budget, positive=True), _micros(wrapup_reserve)
        if wrapup > limit:
            raise ValueError("wrapup_reserve cannot exceed budget")
        task_id = task_id or str(uuid4())
        with self._connect() as db:
            db.execute("""INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (task_id, case_id, variant, workflow, limit, wrapup,
                        max_operations, "running", None, time.time(), None))
        return task_id

    def reserve(
        self, *, task_id: str, model: str, max_cost: str | Decimal,
        operation_key: str | None = None, phase: str = "work",
        request_id: str | None = None,
    ) -> str:
        amount = _micros(max_cost, positive=True)
        if not model.strip() or phase not in ("work", "wrapup"):
            raise ValueError("A model and work/wrapup phase are required")
        request_id = request_id or str(uuid4())
        denied = None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise ValueError("Unknown task")
            used = db.execute("""SELECT COALESCE(SUM(CASE WHEN actual_micros IS NULL
                             THEN reserved_micros ELSE actual_micros END),0) AS cost,
                             COUNT(*) AS calls FROM operations WHERE task_id=?""",
                              (task_id,)).fetchone()
            if task["status"] != "running":
                denied = "Task is no longer running"
            elif operation_key and db.execute("SELECT 1 FROM operations WHERE task_id=? AND operation_key=?",
                                              (task_id, operation_key)).fetchone():
                denied = "Duplicate operation key"
            elif db.execute("SELECT 1 FROM operations WHERE request_id=?", (request_id,)).fetchone():
                denied = "Request ID already used"
            elif task["max_operations"] is not None and used["calls"] >= task["max_operations"]:
                denied = "Operation limit reached"
            elif used["cost"] + amount + (task["wrapup_micros"] if phase == "work" else 0) > task["budget_micros"]:
                denied = "Task budget exhausted"
            if denied:
                db.execute("INSERT INTO events(task_id,kind,reason,created) VALUES (?,?,?,?)",
                           (task_id, "denied", denied, time.time()))
            else:
                db.execute("""INSERT INTO operations(request_id,task_id,operation_key,phase,model,
                            reserved_micros,status,created) VALUES (?,?,?,?,?,?,?,?)""",
                           (request_id, task_id, operation_key, phase, model, amount, "reserved", time.time()))
            db.commit()
        if denied:
            raise AdmissionDenied(denied)
        return request_id

    def settle(self, *, request_id: str, actual_cost: str | Decimal,
               input_tokens: int = 0, output_tokens: int = 0, success: bool = True) -> None:
        amount = _micros(actual_cost)
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            operation = db.execute("SELECT * FROM operations WHERE request_id=?", (request_id,)).fetchone()
            if operation is None:
                raise ValueError("Unknown request ID")
            if operation["status"] == "settled":
                if (operation["actual_micros"], operation["input_tokens"], operation["output_tokens"],
                    bool(operation["success"])) != (amount, input_tokens, output_tokens, success):
                    raise ValueError("Conflicting settlement")
                return
            db.execute("""UPDATE operations SET actual_micros=?, input_tokens=?, output_tokens=?,
                        success=?, status='settled', settled=? WHERE request_id=?""",
                       (amount, input_tokens, output_tokens, int(success), time.time(), request_id))
            db.commit()

    def uncertain(self, request_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE operations SET status='uncertain' WHERE request_id=? AND status='reserved'",
                       (request_id,))

    def finish_task(self, task_id: str, *, accepted: bool, status: str = "completed") -> None:
        if status not in ("completed", "partial", "failed", "stopped"):
            raise ValueError("Invalid final status")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("UPDATE tasks SET status=?, accepted=?, finished=? WHERE id=? AND status='running'",
                          (status, int(accepted), time.time(), task_id)).rowcount != 1:
                raise ValueError("Task missing or already finished")
            db.commit()

    def run_paid_call(
        self, *, task_id: str, model: str, max_cost: str | Decimal,
        execute: Callable[[], Charge], operation_key: str | None = None,
        phase: str = "work",
    ) -> Charge:
        request_id = self.reserve(task_id=task_id, model=model, max_cost=max_cost,
                                  operation_key=operation_key, phase=phase)
        try:
            charge = execute()
            if not isinstance(charge, Charge):
                raise TypeError("execute must return Charge")
            self.settle(request_id=request_id, actual_cost=charge.actual_cost,
                        input_tokens=charge.usage.get("input_tokens", 0),
                        output_tokens=charge.usage.get("output_tokens", 0),
                        success=charge.success)
            return charge
        except BaseException:
            self.uncertain(request_id)
            raise

    def summary(self) -> dict:
        with self._connect() as db:
            tasks = [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY created DESC")]
            operations = [dict(row) for row in db.execute("SELECT * FROM operations ORDER BY created DESC")]
            denials = db.execute("SELECT COUNT(*) FROM events WHERE kind='denied'").fetchone()[0]
        confirmed = sum(op["actual_micros"] or 0 for op in operations)
        reserved = sum(op["reserved_micros"] for op in operations if op["actual_micros"] is None)
        pairs = []
        grouped: dict[str, list[dict]] = {}
        for task in tasks:
            if task["case_id"]:
                grouped.setdefault(task["case_id"], []).append(task)
        for case_id, group in grouped.items():
            if len(group) != 2 or {t["variant"] for t in group} != {"baseline", "candidate"}:
                continue
            if any(t["status"] != "completed" or t["accepted"] != 1 for t in group):
                continue
            if group[0]["workflow"] != group[1]["workflow"]:
                continue
            costs = {}
            for task in group:
                own = [op for op in operations if op["task_id"] == task["id"]]
                if not own or any(op["status"] != "settled" for op in own):
                    break
                costs[task["variant"]] = sum(op["actual_micros"] for op in own)
            if len(costs) == 2:
                pairs.append({"case_id": case_id, "baseline_usd": _usd(costs["baseline"]),
                              "candidate_usd": _usd(costs["candidate"]),
                              "difference_usd": _usd(costs["baseline"] - costs["candidate"])})
        return {"tasks": len(tasks), "accepted": sum(t["accepted"] == 1 for t in tasks),
                "confirmed_usd": _usd(confirmed), "reserved_usd": _usd(reserved),
                "denied": denials, "matched_pairs": pairs}
