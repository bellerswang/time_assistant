from __future__ import annotations

from models import Record
from repositories.base import RecordRepository


class GoogleDocRepository(RecordRepository):
    def __init__(self, google_docs_client=None, doc_id: str | None = None):
        self.client = google_docs_client
        self.doc_id = doc_id

    async def save_record(self, record: Record) -> dict:
        if self.client is None:
            return {"backend": "google_doc", "status": "skipped:not_configured", "doc_id": self.doc_id}
        text = self.render_record(record)
        result = await self.client.append_text(doc_id=self.doc_id, text=text)
        return {"backend": "google_doc", "status": result.get("status", "unknown"), "doc_id": self.doc_id}

    async def get_record(self, record_id: str) -> Record | None:
        return None

    async def list_records(self, category: str | None = None, limit: int = 50) -> list[Record]:
        return []

    async def update_record_category(self, record_id: str, category: str, category_label: str) -> dict:
        return {"backend": "google_doc", "status": "skipped:category_update_not_supported"}

    @staticmethod
    def render_record(record: Record) -> str:
        tags = " / ".join(record.metadata.tags) if record.metadata.tags else "no tags"
        created = record.created_at.strftime("%Y-%m-%d %H:%M")
        return (
            f"\n## {created} · {record.category_label} · {tags}\n\n"
            f"{record.cleaned_text}\n\n"
            f"AI Summary: {record.summary}\n\n"
            f"Record ID:\n{record.id}\n\n"
        )
