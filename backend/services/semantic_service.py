from __future__ import annotations

from models import CATEGORY_LABELS


def normalize_record_category(category: str | None) -> str:
    if category in CATEGORY_LABELS:
        return category
    return "inbox"


def category_label(category: str | None) -> str:
    return CATEGORY_LABELS.get(normalize_record_category(category), CATEGORY_LABELS["inbox"])
