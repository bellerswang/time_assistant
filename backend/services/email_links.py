from __future__ import annotations

import re
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
        or ""
    ).strip()
    if not thread_id:
        # Gmail API message IDs do not identify the conversation route. Keep
        # the supplied URL until the workflow provides the corresponding threadId.
        return current_url

    fragment = parsed.fragment.strip("/")
    path_match = re.match(r"^/mail/u/([^/]+)/?$", parsed.path)
    account = path_match.group(1) if path_match else "0"
    path = f"/mail/u/{quote(account, safe='@._-')}/"

    # Keep provider-supplied message/thread routes, but repair older URLs whose
    # account path was just /mail/ or ended at /mail/u/.
    if parsed.hostname == "mail.google.com" and fragment:
        parts = fragment.split("/")
        if len(parts) >= 2 and parts[-1]:
            return urlunsplit(("https", "mail.google.com", path, "", fragment))

    # Gmail's web client routes to a conversation by its Gmail API threadId.
    return urlunsplit(("https", "mail.google.com", path, "", f"all/{quote(thread_id, safe='')}"))


def normalize_email_source_url(item: dict[str, Any]) -> dict[str, Any]:
    """Copy an email workflow item and repair generic Gmail Inbox URLs."""
    normalized = dict(item)
    url = gmail_message_url(normalized)
    if url:
        normalized["source_url"] = url
    return normalized


def attach_gmail_thread_ids(
    items: list[dict[str, Any]], raw_messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join minimal Gmail raw metadata back onto workflow items before saving."""
    by_message_id: dict[str, list[tuple[str, str]]] = {}
    for raw in raw_messages:
        payload = raw.get("payload")
        message = raw.get("message")
        sources = [raw]
        if isinstance(payload, dict):
            sources.append(payload)
        if isinstance(message, dict):
            sources.append(message)

        message_id = ""
        thread_id = ""
        mailbox = str(raw.get("mailbox") or "").strip().lower()
        for source in sources:
            message_id = message_id or str(
                source.get("source_message_id") or source.get("message_id") or source.get("id") or ""
            ).strip()
            thread_id = thread_id or str(
                source.get("source_thread_id") or source.get("thread_id") or source.get("threadId") or ""
            ).strip()
            mailbox = mailbox or str(source.get("mailbox") or "").strip().lower()
        if message_id and thread_id and ("gmail" in mailbox or "google" in mailbox):
            by_message_id.setdefault(message_id, []).append((mailbox, thread_id))

    joined: list[dict[str, Any]] = []
    for item in items:
        normalized = dict(item)
        mailbox = str(normalized.get("mailbox") or "").strip().lower()
        parsed = urlsplit(str(normalized.get("source_url") or ""))
        is_gmail = "gmail" in mailbox or "google" in mailbox or parsed.hostname == "mail.google.com"
        if is_gmail and not normalized.get("source_thread_id"):
            source_id = str(normalized.get("source_message_id") or "").strip()
            matches = by_message_id.get(source_id, [])
            exact = [thread for raw_mailbox, thread in matches if raw_mailbox == mailbox]
            if exact:
                normalized["source_thread_id"] = exact[0]
            elif len(matches) == 1:
                normalized["source_thread_id"] = matches[0][1]
        joined.append(normalize_email_source_url(normalized))
    return joined
