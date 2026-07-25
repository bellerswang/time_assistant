---
name: email-action-check
description: Run the time_assistant daily mailbox audit over connected Gmail and Hotmail/Outlook. Use to extract every email thread that still requires the user's next action, maintain the Loomi Inbox, and distinguish pending user work from waiting on other people.
---

# Email Action Check

This is the only email workflow skill for time_assistant. It produces the actionable-email list shown in Loomi Inbox.

## Scope

1. Search Gmail and Hotmail/Outlook Inbox, Sent/Sent Items, and relevant archived mail from the past 60 days.
2. Include unresolved threads from earlier runs, even when they are older than the normal lookback period.
3. Paginate broad searches, deduplicate messages by mailbox plus thread ID, and read full thread context whenever responsibility is unclear.
4. Exclude advertisements, newsletters, marketing mail, verification codes, delivery receipts, calendar churn, and completed confirmations. Keep genuine account-security alerts.

## Classify Every Candidate Thread

Classify each reviewed thread as exactly one of:

- `open`: the user must reply, submit a file or form, make a decision, confirm something, attend, or follow up.
- `waiting`: the user has already given a substantive response and another party owns the next step.
- `done`: the thread has a clear completed outcome.
- `dismissed`: the user has explicitly chosen to ignore it.
- `needs_review`: the evidence is insufficient to decide who acts next.

Never treat a message as complete merely because it is read, archived, or old. Reopen a `waiting` item when a later external reply, approaching deadline, missed meeting follow-up, or missing attachment creates a new obligation.

## Decide Who Acts Next

1. Compare the latest meaningful inbound message with the user's latest meaningful sent message. Ignore signatures and quoted history.
2. Treat phrases such as `complete and return`, `please confirm`, `respond within`, `action required`, an attached form, and an explicit deadline as `open` until the thread proves completion.
3. Keep attachment-dependent requests `open` until the requested file was sent or accepted.
4. Treat an unanswered request from the user as `waiting`, not `open`.
5. Use `needs_review` rather than silently excluding any thread whose state is uncertain.
6. Merge the same real-world matter across Gmail and Outlook into one Loomi item, while retaining its source mailbox, source link, and source message ID.

## Persist Results

Create a run, then submit the skill's own classified items through the authenticated local workflow client. Do not print, quote, or expose `WORKFLOW_API_KEY`.

1. Run `python backend/tools/workflow_client.py latest` when prior unresolved workflow context is needed.
2. Run `python backend/tools/workflow_client.py create-run` and read the returned run ID.
3. Write the result JSON to a temporary local file, then run `python backend/tools/workflow_client.py submit-result --run-id <run_id> --input <temporary-json-file>`.
4. Never use the browser's Firebase token, localhost API, or direct unauthenticated HTTP requests for this workflow.

Use the second request body:

```json
{
  "items": [],
  "raw_messages": [],
  "status": "succeeded"
}
```

Do not send full email bodies to Firestore. Each resulting Loomi item must include `mailbox`, `title`, `search_clues`, `event_summary`, `action_required`, `status`, `source_url`, and `source_message_id`. Store only minimal source metadata in `raw_messages`.

## Output And Safety

Report the number of `open`, `waiting`, and `needs_review` threads, with `open` as the user's actionable count. Report the search window and any incomplete mailbox coverage.

Do not send, reply to, archive, delete, label, mark as read, or otherwise modify any email.
