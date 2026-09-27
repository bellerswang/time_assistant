from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


def gmail_message_url(item: dict[str, Any]) -> str:
    """Return a Gmail conversation URL when a Gmail thread identifier is available."""
    mailbox = str(item.get("mailbox") or "").strip().lower()
    current_url = str(item.get("source_url") or "").strip()
    parsed = urlsplit(current_url)
    is_gmail = "gmail" in mailbox or parsed.hostname == "mail.google.com"
    if not is_gmail:
        return current_url

    thread_id = str(
        item.get("source_thread_id")
        or item.get("thread_id")
        or item.get("threadId")
        or item.get("conversation_id")
        or item.get("conversationId")
        or item.get("source_message_id")
        or item.get("message_id")
        or item.get("id")
        or ""
    ).strip()
    if not thread_id:
        return current_url

    # Keep valid provider-supplied deep links. Generic Inbox/All Mail links need
    # a Gmail thread ID appended so opening the card locates the conversation.
    fragment = parsed.fragment.strip("/")
    if parsed.hostname == "mail.google.com" and fragment:
        parts = fragment.split("/")
        if len(parts) >= 2 and parts[-1]:
            return current_url

    path = parsed.path if parsed.hostname == "mail.google.com" and parsed.path else "/mail/u/0/"
    # Gmail's web client routes to a conversation by its Gmail API threadId.
    return urlunsplit(("https", "mail.google.com", path, "", f"all/{quote(thread_id, safe='')}"))


def normalize_email_source_url(item: dict[str, Any]) -> dict[str, Any]:
    """Copy an email workflow item and repair generic Gmail Inbox URLs."""
    normalized = dict(item)
    url = gmail_message_url(normalized)
    if url:
        normalized["source_url"] = url
    return normalized
