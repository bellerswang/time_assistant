from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def ensure_workflow_schema(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                since_date TEXT NOT NULL,
                until_date TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_items (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                mailbox TEXT NOT NULL,
                title TEXT NOT NULL,
                search_clues TEXT NOT NULL,
                event_summary TEXT NOT NULL,
                action_required TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                source_url TEXT,
                source_message_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES workflow_runs(id)
            );
            CREATE TABLE IF NOT EXISTS workflow_raw_messages (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                mailbox TEXT NOT NULL,
                message_id TEXT NOT NULL,
                thread_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES workflow_runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_created ON workflow_runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_workflow_items_run ON workflow_items(run_id);
            """
        )
        conn.commit()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def create_run(db_path: str, workflow_name: str = "email-action-check", days: int = 60) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_id = f"{workflow_name}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    since = (now.date() - timedelta(days=days - 1)).isoformat()
    until = now.date().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, started_at, status, since_date, until_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, workflow_name, now.isoformat(), "running", since, until, now.isoformat()),
        )
        conn.commit()
    return {"id": run_id, "workflow_name": workflow_name, "started_at": now.isoformat(), "status": "running", "since_date": since, "until_date": until}


def finish_run(db_path: str, run_id: str, status: str = "succeeded", error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE workflow_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?", (now, status, error, run_id))
        conn.commit()


def save_result(db_path: str, run_id: str, items: list[dict[str, Any]], raw_messages: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        for item in items:
            conn.execute(
                "INSERT OR REPLACE INTO workflow_items (id, run_id, mailbox, title, search_clues, event_summary, action_required, status, source_url, source_message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], run_id, item.get("mailbox", ""), item.get("title", ""), item.get("search_clues", ""), item.get("event_summary", ""), item.get("action_required", ""), item.get("status", "open"), item.get("source_url"), item.get("source_message_id"), now),
            )
        for raw in raw_messages:
            conn.execute(
                "INSERT OR REPLACE INTO workflow_raw_messages (id, run_id, mailbox, message_id, thread_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (raw["id"], run_id, raw.get("mailbox", ""), raw.get("message_id", ""), raw.get("thread_id"), json.dumps(raw.get("payload", raw), ensure_ascii=False), now),
            )
        conn.commit()


def latest_run(db_path: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if not run:
            return None
        items = conn.execute("SELECT * FROM workflow_items WHERE run_id = ? ORDER BY status, created_at", (run["id"],)).fetchall()
        raw_count = conn.execute("SELECT COUNT(*) FROM workflow_raw_messages WHERE run_id = ?", (run["id"],)).fetchone()[0]
    result = _row(run)
    result["items"] = [_row(item) for item in items]
    result["raw_count"] = raw_count
    return result


def list_runs(db_path: str, limit: int = 30) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(row) for row in rows]


def get_run(db_path: str, run_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
        items = conn.execute("SELECT * FROM workflow_items WHERE run_id = ? ORDER BY status, created_at", (run_id,)).fetchall()
        raw_count = conn.execute("SELECT COUNT(*) FROM workflow_raw_messages WHERE run_id = ?", (run_id,)).fetchone()[0]
    if not run:
        return None
    result = _row(run)
    result["items"] = [_row(item) for item in items]
    result["raw_count"] = raw_count
    return result


def update_item_status(db_path: str, item_id: str, status: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        result = conn.execute("UPDATE workflow_items SET status = ? WHERE id = ?", (status, item_id))
        conn.commit()
    return result.rowcount > 0
