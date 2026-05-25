from __future__ import annotations

from abc import ABC, abstractmethod

from models import Record


class RecordRepository(ABC):
    @abstractmethod
    async def save_record(self, record: Record) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def get_record(self, record_id: str) -> Record | None:
        raise NotImplementedError

    @abstractmethod
    async def list_records(self, category: str | None = None, limit: int = 50) -> list[Record]:
        raise NotImplementedError

    @abstractmethod
    async def update_record_category(self, record_id: str, category: str, category_label: str) -> dict:
        raise NotImplementedError
