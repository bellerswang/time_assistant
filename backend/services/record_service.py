from __future__ import annotations

from models import Record


class RecordService:
    def __init__(self, primary_repository=None, index_repository=None):
        self.primary_repository = primary_repository
        self.index_repository = index_repository

    async def save_record(self, record: Record) -> dict:
        primary_result = None
        if self.primary_repository:
            primary_result = await self.primary_repository.save_record(record)

        index_result = None
        if self.index_repository:
            index_result = await self.index_repository.save_record(record)

        return {
            "record_id": record.id,
            "primary": primary_result,
            "index": index_result,
        }
