from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any


NOISE = re.compile(r"newsletter|unsubscribe|promotion|promotional|sale|offer|marketing|otp|one[- ]time|verification code|验证码|广告|订阅", re.I)


def _text(value: Any) -> str:
    return str(value or "").strip()


AD_NOISE = re.compile(
    r"advert|advertisement|discount|limited time|last chance|free .*month|\d+ months? .*free|free trial|"
    r"airdrop|crypto|casino|flight deal|travel deal|from just \$?\d|just \$?\d",
    re.I,
)


def _date(value: Any) -> datetime:
    raw = _text(value)
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _message_date(message: dict[str, Any]) -> datetime:
    """Accept the common Gmail, Outlook, and workflow-normalized timestamp names."""
    return _date(
        message.get("date")
        or message.get("received_at")
        or message.get("sent_at")
        or message.get("email_ts")
        or message.get("receivedDateTime")
        or message.get("sentDateTime")
    )


def _subject(message: dict[str, Any]) -> str:
    return _text(message.get("subject") or message.get("title") or "(无主题)")


def _thread_key(message: dict[str, Any]) -> str:
    thread = _text(message.get("thread_id") or message.get("threadId"))
    if thread:
        return thread
    subject = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", _subject(message), flags=re.I)
    return re.sub(r"\W+", " ", subject.lower()).strip()


def _is_noise(message: dict[str, Any]) -> bool:
    haystack = " ".join(
        _text(message.get(k))
        for k in ("subject", "title", "from", "sender", "snippet", "body", "labels", "categories")
    )
    return bool(NOISE.search(haystack) or AD_NOISE.search(haystack))


def _stable_id(mailbox: str, key: str) -> str:
    return "email-" + hashlib.sha1(f"{mailbox}:{key}".encode("utf-8")).hexdigest()[:20]


def build_workflow_items(inbox_messages: list[dict[str, Any]], sent_messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn connector results into deduplicated actionable items and raw snapshots."""
    all_messages: list[tuple[str, dict[str, Any], str]] = []
    raw: list[dict[str, Any]] = []
    for mailbox, messages, direction in (("Gmail", inbox_messages, "inbound"), ("Gmail", sent_messages, "sent")):
        for message in messages:
            item = dict(message)
            item.setdefault("direction", direction)
            item.setdefault("mailbox", mailbox)
            all_messages.append((mailbox, item, direction))
    # A caller may provide mailbox on each message (Hotmail/Outlook); preserve it.
    grouped: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for mailbox, message, direction in all_messages:
        mailbox = _text(message.get("mailbox")) or mailbox
        message_id = _text(message.get("message_id") or message.get("id")) or _stable_id(mailbox, _subject(message))
        raw.append({"id": f"raw-{message_id}", "mailbox": mailbox, "message_id": message_id, "thread_id": _thread_key(message), "payload": message})
        grouped.setdefault(_thread_key(message), []).append((message, direction))

    items: list[dict[str, Any]] = []
    for thread_key, messages in grouped.items():
        latest_inbound = max((m for m, d in messages if d != "sent"), key=_message_date, default=None)
        latest_sent = max((m for m, d in messages if d == "sent"), key=_message_date, default=None)
        if not latest_inbound or _is_noise(latest_inbound):
            continue
        inbound_time = _message_date(latest_inbound)
        sent_time = _message_date(latest_sent) if latest_sent else datetime.min.replace(tzinfo=timezone.utc)
        status = "waiting" if latest_sent and sent_time >= inbound_time else "open"
        mailbox_key = _text(latest_inbound.get("mailbox")) or "Gmail"
        source_id = _text(latest_inbound.get("message_id") or latest_inbound.get("id")) or _stable_id(mailbox_key, thread_key)
        title = _subject(latest_inbound)
        sender = _text(latest_inbound.get("from") or latest_inbound.get("sender"))
        snippet = _text(latest_inbound.get("snippet") or latest_inbound.get("body"))
        summary = snippet[:240] or f"来自 {sender or '发件人'} 的邮件"
        action = _text(latest_inbound.get("action_required")) or ("等待对方处理/回复" if status == "waiting" else "阅读邮件并完成邮件中要求的下一步")
        clues = f"主题: {title}; 发件人: {sender or '未知'}; 邮件ID: {source_id}"
        items.append({"id": _stable_id("merged", thread_key), "mailbox": mailbox_key, "title": title, "search_clues": clues, "event_summary": summary, "action_required": action, "status": status, "source_url": _text(latest_inbound.get("source_url") or latest_inbound.get("web_url") or latest_inbound.get("web_link") or latest_inbound.get("display_url") or latest_inbound.get("url")), "source_message_id": source_id})
    return items, raw
