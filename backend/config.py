from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    storage_mode: str = os.getenv("STORAGE_MODE", "google_doc")
    index_mode: str = os.getenv("INDEX_MODE", "sqlite")
    google_docs_enabled: bool = os.getenv("GOOGLE_DOCS_ENABLED", "true").lower() not in {"0", "false", "no"}
    google_docs_default_doc_id: str | None = os.getenv("GOOGLE_DOCS_DEFAULT_DOC_ID") or None
    firestore_enabled: bool = os.getenv("FIRESTORE_ENABLED", "false").lower() in {"1", "true", "yes"}
    firestore_project_id: str | None = os.getenv("FIRESTORE_PROJECT_ID") or None
    firestore_collection: str = os.getenv("FIRESTORE_COLLECTION", "records")
