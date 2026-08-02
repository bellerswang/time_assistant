import os
import sys
import tempfile
from pathlib import Path
import shutil
import unittest

import httpx


TEST_DIR = Path(tempfile.mkdtemp(prefix="loomi-notebook-tests-"))
os.environ["FIRESTORE_ENABLED"] = "false"
os.environ["LOOMI_INGEST_API_KEY"] = "test-key"
os.environ["ALLOWED_FIREBASE_UID"] = ""
os.environ["VOICE_DB_PATH"] = str(TEST_DIR / "chronoai.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


class NotebookApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    @staticmethod
    def payload(item_id="test-thread"):
        return {
            "schema_version": "1.0",
            "source": {
                "app": "codex",
                "item_id": item_id,
                "title": "Notebook test",
                "project_name": "time_assistant",
            },
            "note": {
                "title": "Notebook test note",
                "summary": "A short test summary.",
                "body_markdown": "# Test\n\nOriginal body.",
                "tags": ["test", "notebook"],
            },
        }

    async def ingest(self, payload):
        return await self.client.post(
            "/api/integrations/notebook/ingest",
            headers={"X-Loomi-Ingest-Key": "test-key"},
            json=payload,
        )

    async def test_ingest_is_idempotent_and_revisioned(self):
        payload = self.payload()
        created = await self.ingest(payload)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["operation"], "created")
        self.assertEqual(created.json()["version"], 1)

        unchanged = await self.ingest(payload)
        self.assertEqual(unchanged.json()["operation"], "unchanged")
        self.assertEqual(unchanged.json()["version"], 1)

        payload["note"]["body_markdown"] = "# Test\n\nChanged body."
        updated = await self.ingest(payload)
        self.assertEqual(updated.json()["operation"], "updated")
        self.assertEqual(updated.json()["version"], 2)

        revisions = await main.list_notebook_revisions(updated.json()["note_id"])
        self.assertEqual([item["version"] for item in revisions], [1])
        self.assertEqual(revisions[0]["body_markdown"], "# Test\n\nOriginal body.")

    async def test_ingest_key_is_required_and_app_api_is_protected(self):
        unauthorized_ingest = await self.client.post(
            "/api/integrations/notebook/ingest",
            headers={"X-Loomi-Ingest-Key": "wrong-key"},
            json=self.payload("auth-thread"),
        )
        self.assertEqual(unauthorized_ingest.status_code, 401)

        unauthorized_list = await self.client.get("/api/notebook/notes")
        self.assertEqual(unauthorized_list.status_code, 401)

    async def test_invalid_payload_is_rejected(self):
        payload = self.payload("invalid-thread")
        payload["note"]["body_markdown"] = ""
        response = await self.ingest(payload)
        self.assertEqual(response.status_code, 400)


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
