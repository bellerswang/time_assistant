# Portfolio Intelligence → Loomi

The **要闻阅读** page reads Firestore `investment_reports`, one document per London report date. The report is labelled `pending_review`; publishing it to Loomi does not approve or merge the Portfolio Intelligence Site's research state.

After the ChatGPT task creates `portfolio-intelligence-draft-YYYY-MM-DD.json` and its Chinese **今天值得看什么** summary, a publisher must send both to the private Loomi backend:

`POST /api/workflows/investment-reports/ingest`

The publisher authenticates with the `X-Investment-Report-Key` header. The corresponding `INVESTMENT_REPORT_API_KEY` stays in a server-side secret and the publisher's secret store; never put it in the task prompt, browser code, report, or URL. The JSON body has `date` (`YYYY-MM-DD`), `title`, `summary`, `body_markdown`, optional `source_links`, and optional complete `draft_json`. Repeating the same date replaces that day's draft. The authenticated app can download the complete JSON from `/api/investment-reports/YYYY-MM-DD/draft`.

For a desktop task that runs with local project files, `backend/tools/publish_investment_report.py --draft <JSON path> --summary <Markdown path> --base-url <private Loomi HTTPS origin>` performs this upload after both files exist. The task should report publication as successful only after the endpoint returns `ok: true`. A web-only ChatGPT scheduled task needs an approved connected publishing tool that can call this endpoint with its own stored secret; the task prompt alone cannot grant it an HTTP action or access to the key.

The **爬虫 Link** page writes to `projects/mercurial-weft-455321-v6/databases/(default)/documents/crawler_links`. Each document has `id`, `url`, `status: pending`, `created_at`, and `source: loomi`. The app shows the project and collection after upload. The crawler should read `crawler_links` with its own server-side Firestore credentials and only process `status == "pending"`.
