from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore


class FirestoreWorkflowService:
    """Persistent email workflow storage shared by Cloud Run and every client."""

    def __init__(
        self,
        db: firestore.AsyncClient,
        runs_collection: str = "email_workflow_runs",
        items_collection: str = "email_action_items",
    ) -> None:
        self.db = db
        self.runs = db.collection(runs_collection)
        self.items = db.collection(items_collection)

    async def create_run(self, workflow_name: str = "email-action-check", days: int = 60) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        run_id = f"{workflow_name}-{now.strftime('%Y%m%dT%H%M%SZ')}"
        payload = {
            "id": run_id,
            "workflow_name": workflow_name,
            "started_at": now,
            "finished_at": None,
            "status": "running",
            "since_date": (now.date() - timedelta(days=days - 1)).isoformat(),
            "until_date": now.date().isoformat(),
            "error": None,
            "raw_count": 0,
            "item_count": 0,
            "status_counts": {},
            "created_at": now,
        }
        await self.runs.document(run_id).set(payload)
        return self._public_run(payload)

    async def save_result(self, run_id: str, items: list[dict[str, Any]], raw_count: int) -> None:
        now = datetime.now(timezone.utc)
        status_counts: Counter[str] = Counter()
        for item in items:
            item_id = str(item["id"])
            doc_ref = self.items.document(item_id)
            previous = await doc_ref.get()
            previous_data = previous.to_dict() if previous.exists else {}
            source_message_id = str(item.get("source_message_id") or "")

            # Preserve a user's completed/dismissed decision until the thread receives a new message.
            status = str(item.get("status") or "open")
            if (
                previous_data.get("source_message_id") == source_message_id
                and previous_data.get("status") in {"done", "dismissed"}
            ):
                status = previous_data["status"]

            payload = {
                **item,
                "id": item_id,
                "status": status,
                "latest_run_id": run_id,
                "first_seen_at": previous_data.get("first_seen_at", now),
                "last_seen_at": now,
                "updated_at": now,
            }
            await doc_ref.set(payload, merge=True)
            status_counts[status] += 1

        await self.runs.document(run_id).update(
            {
                "raw_count": raw_count,
                "item_count": len(items),
                "status_counts": dict(status_counts),
                "finished_at": now,
                "status": "succeeded",
                "error": None,
            }
        )

    async def fail_run(self, run_id: str, error: str) -> None:
        await self.runs.document(run_id).update(
            {
                "finished_at": datetime.now(timezone.utc),
                "status": "failed",
                "error": error,
            }
        )

    async def latest_run(self) -> dict[str, Any] | None:
        docs = await self.runs.order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).get()
        if not docs:
            return None
        return await self.get_run(docs[0].id)

    async def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        docs = await self.runs.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit).get()
        return [self._public_run(doc.to_dict()) for doc in docs]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        run_doc = await self.runs.document(run_id).get()
        if not run_doc.exists:
            return None
        item_docs = await self.items.where("latest_run_id", "==", run_id).get()
        result = self._public_run(run_doc.to_dict())
        result["items"] = sorted(
            [self._public_item(doc.to_dict()) for doc in item_docs],
            key=lambda item: (item.get("status", ""), item.get("title", "")),
        )
        return result

    async def update_item_status(self, item_id: str, status: str) -> bool:
        doc_ref = self.items.document(item_id)
        if not (await doc_ref.get()).exists:
            return False
        await doc_ref.update({"status": status, "updated_at": datetime.now(timezone.utc)})
        return True

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _public_run(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: self._serialize(value) for key, value in data.items()}

    def _public_item(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: self._serialize(value) for key, value in data.items()}
