"""Publish a completed Portfolio Intelligence draft to private Loomi."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True, help="portfolio-intelligence-draft-YYYY-MM-DD.json")
    parser.add_argument("--summary", type=Path, required=True, help="The Chinese 今日值得看什么 Markdown summary")
    parser.add_argument("--base-url", default=os.getenv("LOOMI_PUBLIC_ORIGIN", ""))
    args = parser.parse_args()

    match = re.fullmatch(r"portfolio-intelligence-draft-(\d{4}-\d{2}-\d{2})\.json", args.draft.name)
    if not match:
        parser.error("Draft filename must be portfolio-intelligence-draft-YYYY-MM-DD.json")
    if not args.base_url.startswith("https://"):
        parser.error("Set --base-url to the private HTTPS Loomi origin")
    key = os.getenv("INVESTMENT_REPORT_API_KEY", "")
    if not key:
        parser.error("INVESTMENT_REPORT_API_KEY is not configured")

    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        parser.error("Draft JSON must be an object")
    body = args.summary.read_text(encoding="utf-8").strip()
    if not body:
        parser.error("Summary is empty")
    date = match.group(1)
    payload = {
        "date": date,
        "title": f"Portfolio Intelligence · {date}",
        "summary": body[:300],
        "body_markdown": body,
        "draft_json": draft,
        "source_links": [],
    }
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/workflows/investment-reports/ingest",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Investment-Report-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    print(result["document_path"])


if __name__ == "__main__":
    main()
