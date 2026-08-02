from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RecordCategory = Literal[
    "work_idea",
    "family_plan",
    "life_knowledge",
    "self_reflection",
    "ask",
    "notebook",
    "inbox",
]


CATEGORY_LABELS: dict[str, str] = {
    "work_idea": "Work Idea",
    "family_plan": "Family Plan",
    "life_knowledge": "Life Knowledge",
    "self_reflection": "Self Reflection",
    "ask": "Ask",
    "notebook": "Notebook",
    "inbox": "Inbox",
}


class RecordMetadata(BaseModel):
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    time_expression: str | None = None
    action_required: bool = False
    calendar_candidate: bool = False
    source_title: str | None = None
    project_name: str | None = None
    content_format: Literal["plain_text", "markdown"] = "plain_text"


class Record(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    source: Literal["voice", "text", "codex"]
    raw_transcript: str
    cleaned_text: str
    content_markdown: str | None = None
    category: RecordCategory
    category_label: str
    confidence: float = 0.5
    needs_review: bool = False
    title: str
    summary: str
    metadata: RecordMetadata = Field(default_factory=RecordMetadata)
    storage_status: dict[str, Any] = Field(default_factory=dict)
    status: Literal["active", "archived", "trashed"] = "active"
    version: int = 1
    external_key_hash: str | None = None
    content_hash: str | None = None
