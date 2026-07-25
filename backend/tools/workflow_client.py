"""Authenticated client for the scheduled email workflow API.

The workflow key is loaded from the local backend/.env or process environment
and is never included in command output.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import httpx
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
BASE_URL = os.getenv(
    "WORKFLOW_API_URL",
    "https://voice-assistant-1090997558704.europe-west2.run.app",
).rstrip("/")
WORKFLOW_KEY = os.getenv("WORKFLOW_API_KEY", "").strip()


def request(method: str, path: str, payload: dict | None = None) -> None:
    if not WORKFLOW_KEY:
        raise RuntimeError("WORKFLOW_API_KEY is not configured in backend/.env or the environment.")
    response = httpx.request(
        method,
        f"{BASE_URL}{path}",
        headers={"X-Workflow-Key": WORKFLOW_KEY},
        json=payload,
        timeout=45,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Workflow API returned HTTP {response.status_code}: {response.text[:1000]}")
    print(response.text)


def read_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description="Call Loomi's authenticated email workflow API")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("latest")
    sub.add_parser("runs")
    sub.add_parser("create-run")
    result_parser = sub.add_parser("submit-result")
    result_parser.add_argument("--run-id", required=True)
    result_parser.add_argument("--input", required=True, help="JSON file path, or - for stdin")
    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("--input", required=True, help="JSON file path, or - for stdin")
    args = parser.parse_args()

    if args.command == "latest":
        request("GET", "/api/workflows/email-action-check/latest")
    elif args.command == "runs":
        request("GET", "/api/workflows/email-action-check/runs")
    elif args.command == "create-run":
        request("POST", "/api/workflows/email-action-check/runs")
    elif args.command == "submit-result":
        request("POST", f"/api/workflows/email-action-check/runs/{args.run_id}/result", read_json(args.input))
    elif args.command == "ingest":
        request("POST", "/api/workflows/email-action-check/ingest", read_json(args.input))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
