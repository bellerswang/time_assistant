from __future__ import annotations

import json
import sqlite3

from models import Record, RecordMetadata
from repositories.base import RecordRepository


class SQLiteRepository(RecordRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def save_record(self, record: Record) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO records (
                    id, created_at, updated_at, source, raw_transcript, cleaned_text,
                    category, category_label, confidence, needs_review, title, summary,
                    metadata_json, storage_status_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.source,
                    record.raw_transcript,
                    record.cleaned_text,
                    record.category,
                    record.category_label,
                    record.confidence,
                    1 if record.needs_review else 0,
                    record.title,
                    record.summary,
                    json.dumps(record.metadata.model_dump(), ensure_ascii=False),
                    json.dumps(record.storage_status, ensure_ascii=False),
                ),
            )
            conn.commit()
        return {"backend": "sqlite", "status": "saved"}

    async def get_record(self, record_id: str) -> Record | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    async def list_records(self, category: str | None = None, limit: int = 50) -> list[Record]:
        params = []
        clause = ""
        if category:
            clause = "WHERE category = ?"
            params.append(category)
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"SELECT * FROM records {clause} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        return [record for row in rows if (record := self._row_to_record(row))]

    async def update_record_category(self, record_id: str, category: str, category_label: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "UPDATE records SET category = ?, category_label = ? WHERE id = ?",
                (category, category_label, record_id),
            )
            conn.commit()
        return {"backend": "sqlite", "status": "updated" if result.rowcount else "not_found"}

    @staticmethod
    def _row_to_record(row: sqlite3.Row | None) -> Record | None:
        if row is None:
            return None
        metadata = RecordMetadata(**json.loads(row["metadata_json"] or "{}"))
        return Record(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source=row["source"],
            raw_transcript=row["raw_transcript"],
            cleaned_text=row["cleaned_text"],
            category=row["category"],
            category_label=row["category_label"],
            confidence=row["confidence"],
            needs_review=bool(row["needs_review"]),
            title=row["title"],
            summary=row["summary"],
            metadata=metadata,
            storage_status=json.loads(row["storage_status_json"] or "{}"),
        )
