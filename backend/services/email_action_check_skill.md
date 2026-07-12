---
name: email-action-check
description: Run the time_assistant email workflow over connected Gmail and Hotmail/Outlook mailboxes for the past 60 days.
---

# Email Action Check

这是 time_assistant 的正式邮件 Workflow。每次运行检查 Gmail 和 Hotmail/Outlook 的收件箱、已发送邮件和完整线程，识别仍需用户处理的事项，并把原始快照与结构化结果写入 time_assistant。

## Rules

1. 查询过去 60 个自然日，覆盖 Inbox 和 Sent/Sent Items。
2. 优先读取个人邮件、付款、账户安全、预约、退货、截止日期、资料提交和明确要求回复的完整线程。
3. 排除广告、普通订阅、验证码和已完成确认；账户安全提醒除外。
4. 比较入站与用户最新已发送邮件：用户已完成请求且当前只是等待对方时，状态写为 `waiting`，不能列为待回复。
5. Gmail 与 Hotmail 的同一事项只保留一行，使用稳定主题/案件号/线程线索去重。
6. 不发送、回复、归档、删除、标记已读、加标签或执行任何邮件写操作。

## Persistence

将连接器返回的邮件摘要、正文片段、日期、发件人、主题、message/thread id 和可打开链接作为 `raw_messages`，将结构化待办作为 `items`，POST 到 `http://127.0.0.1:11338/api/workflows/email-action-check/ingest`，请求 JSON 为 `{"inbox_messages": [...], "sent_messages": [...]}`。

App 的 Workflow 页面是唯一日常查看入口，不要把 HTML 表格直接贴进聊天窗口。每个 item 必须至少包含 `mailbox`、`title`、`search_clues`、`event_summary`、`action_required`、`status`、`source_url`、`source_message_id`。
