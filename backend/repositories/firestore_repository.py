from __future__ import annotations

from models import Record
from repositories.base import RecordRepository


class FirestoreRepository(RecordRepository):
    def __init__(self, project_id: str | None, collection_name: str = "records"):
        self.project_id = project_id
        self.collection_name = collection_name

    async def save_record(self, record: Record) -> dict:
        raise NotImplementedError("Firestore storage is reserved but not enabled yet.")

    async def get_record(self, record_id: str) -> Record | None:
        raise NotImplementedError("Firestore storage is reserved but not enabled yet.")

    async def list_records(self, category: str | None = None, limit: int = 50) -> list[Record]:
        raise NotImplementedError("Firestore storage is reserved but not enabled yet.")

    async def update_record_category(self, record_id: str, category: str, category_label: str) -> dict:
        raise NotImplementedError("Firestore storage is reserved but not enabled yet.")
