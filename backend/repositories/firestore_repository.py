from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from google.cloud import firestore

try:
    from google.cloud.firestore_v1.vector import Vector
except ImportError:
    try:
        from google.cloud.firestore import Vector
    except ImportError:
        Vector = None

from models import Record, RecordMetadata
from repositories.base import RecordRepository


class FirestoreRepository(RecordRepository):
    def __init__(self, credentials: Any = None, project_id: str | None = None, collection_name: str = "records"):
        self.project_id = project_id
        self.collection_name = collection_name
        self.db = firestore.AsyncClient(credentials=credentials, project=project_id)
        self.sync_db = firestore.Client(credentials=credentials, project=project_id)


    async def save_record(self, record: Record, embedding: list[float] | None = None) -> dict:
        data = record.model_dump(mode="json")
        # Firestore's python SDK handles native datetime beautifully. 
        # We ensure standard timezone-aware datetime objects are stored.
        data["created_at"] = record.created_at
        data["updated_at"] = record.updated_at
        
        if embedding and Vector is not None:
            data["embedding"] = Vector(embedding)
        
        doc_ref = self.db.collection(self.collection_name).document(record.id)
        await doc_ref.set(data)
        return {"backend": "firestore", "status": "saved", "doc_id": record.id}

    async def search_vector_nearest(
        self,
        query_embedding: list[float],
        category_filter: list[str] | None = None,
        limit: int = 8
    ) -> list[Record]:
        if Vector is None:
            raise RuntimeError("Firestore Vector Search is not supported by installed package version.")
            
        import asyncio
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        
        loop = asyncio.get_event_loop()
        
        def run_sync_query():
            collection_ref = self.sync_db.collection(self.collection_name)
            query = collection_ref.find_nearest(
                vector_field="embedding",
                query_vector=Vector(query_embedding),
                distance_measure=DistanceMeasure.COSINE,
                limit=limit * 2
            )
            return query.get()
            
        docs = await loop.run_in_executor(None, run_sync_query)
        records = []
        for doc in docs:
            data = doc.to_dict()
            if record := self._dict_to_record(data):
                if category_filter and record.category not in category_filter:
                    continue
                records.append(record)
                if len(records) >= limit:
                    break
        return records

    async def list_records_in_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 50
    ) -> list[Record]:
        query = self.db.collection(self.collection_name)
        # Firestore handles native datetime queries correctly.
        query = query.where("created_at", ">=", start_date).where("created_at", "<=", end_date)
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        docs = await query.get()
        records = []
        for doc in docs:
            data = doc.to_dict()
            if record := self._dict_to_record(data):
                records.append(record)
        return records

    async def get_record(self, record_id: str) -> Record | None:
        doc_ref = self.db.collection(self.collection_name).document(record_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return self._dict_to_record(data)

    async def list_records(self, category: str | None = None, limit: int = 50) -> list[Record]:
        query = self.db.collection(self.collection_name)
        if category and category != "all":
            query = query.where("category", "==", category)
        # Order by created_at descending
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        docs = await query.get()
        records = []
        for doc in docs:
            data = doc.to_dict()
            if record := self._dict_to_record(data):
                records.append(record)
        return records

    async def search_records(self, query_text: str, category: str | None = None, limit: int = 10) -> list[Record]:
        query_text = (query_text or "").strip().lower()
        records = await self.list_records(category=category, limit=max(limit * 8, 80))
        if not query_text:
            return records[:limit]

        def haystack(record: Record) -> str:
            return " ".join(
                [
                    record.title,
                    record.summary,
                    record.cleaned_text,
                    record.raw_transcript,
                    record.category_label,
                    " ".join(record.metadata.tags),
                ]
            ).lower()

        return [record for record in records if query_text in haystack(record)][:limit]

    async def update_record(self, record_id: str, updates: dict[str, Any]) -> dict:
        allowed = {
            "title",
            "summary",
            "cleaned_text",
            "raw_transcript",
            "category",
            "category_label",
            "needs_review",
        }
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            return {"backend": "firestore", "status": "skipped:no_updates"}
        payload["updated_at"] = datetime.now(timezone.utc)
        doc_ref = self.db.collection(self.collection_name).document(record_id)
        await doc_ref.update(payload)
        return {"backend": "firestore", "status": "updated"}

    async def update_record_category(self, record_id: str, category: str, category_label: str) -> dict:
        doc_ref = self.db.collection(self.collection_name).document(record_id)
        await doc_ref.update({
            "category": category,
            "category_label": category_label,
            "updated_at": datetime.now(timezone.utc)
        })
        return {"backend": "firestore", "status": "updated"}

    async def delete_record(self, record_id: str) -> dict:
        doc_ref = self.db.collection(self.collection_name).document(record_id)
        await doc_ref.delete()
        return {"backend": "firestore", "status": "deleted"}

    def _dict_to_record(self, data: dict[str, Any]) -> Record | None:
        if not data:
            return None
        
        metadata_data = data.get("metadata", {})
        metadata = RecordMetadata(
            people=metadata_data.get("people", []),
            places=metadata_data.get("places", []),
            tags=metadata_data.get("tags", []),
            time_expression=metadata_data.get("time_expression"),
            action_required=metadata_data.get("action_required", False),
            calendar_candidate=metadata_data.get("calendar_candidate", False)
        )
        
        # Parse created_at / updated_at in case they are stored as strings or ISO format
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
            
        updated_at = data["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return Record(
            id=data["id"],
            created_at=created_at,
            updated_at=updated_at,
            source=data.get("source", "voice"),
            raw_transcript=data["raw_transcript"],
            cleaned_text=data["cleaned_text"],
            category=data["category"],
            category_label=data["category_label"],
            confidence=data.get("confidence", 0.5),
            needs_review=bool(data.get("needs_review", False)),
            title=data["title"],
            summary=data["summary"],
            metadata=metadata,
            storage_status=data.get("storage_status", {})
        )
