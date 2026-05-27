from fastapi import FastAPI, HTTPException, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import json
import tempfile
import logging
import sqlite3
import uuid
import re
import base64
from datetime import datetime, timezone
import httpx

from models import CATEGORY_LABELS, Record, RecordMetadata

try:
    from google.cloud import storage
except ImportError:
    storage = None

try:
    import google.auth as google_auth
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:
    google_auth = None
    service_account = None
    build = None

# Load .env file from backend directory explicitly using absolute path
backend_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(backend_dir)
load_dotenv(dotenv_path=os.path.join(backend_dir, ".env"))

# Use uvicorn's error logger so logs appear nicely in --reload subprocess consoles
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="ChronoAI Backend Server v2.0")

# CORS config: allow local browser files and LAN mobile devices
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_key = os.getenv("OPENAI_API_KEY")
if not openai_key:
    # Try reading from openai_key.txt in project root as fallback
    try:
        txt_path = os.path.join(root_dir, "openai_key.txt")
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                openai_key = f.read().strip()
                logger.info("Loaded OPENAI_API_KEY from openai_key.txt")
    except Exception as e:
        logger.error(f"Failed to read openai_key.txt: {e}")

# Handle comma-separated keys like: time_assistant,sk-proj-...
if openai_key and "," in openai_key:
    openai_key = openai_key.split(",")[1].strip()
    logger.info("Parsed comma-separated API key successfully")

if not openai_key or not openai_key.startswith("sk-"):
    logger.warning("OPENAI_API_KEY is not configured or invalid! Server will run but API calls will fail with 401/402.")

client = AsyncOpenAI(
    api_key=openai_key if openai_key and openai_key.startswith("sk-") else "placeholder",
    http_client=httpx.AsyncClient()
)

async def get_text_embedding(text: str) -> list[float] | None:
    if not openai_key or openai_key == "placeholder":
        return None
    try:
        logger.info(f"[Embedding] Generating embedding for text snippet of length {len(text)}")
        response = await client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"[Embedding] Failed to generate embedding: {e}")
        return None

VOICE_TRANSCRIBE_MODEL = os.getenv("VOICE_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
VOICE_DB_PATH = os.getenv("VOICE_DB_PATH", os.path.join(backend_dir, "data", "chronoai.db"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
if DEEPSEEK_MODEL:
    DEEPSEEK_MODEL = DEEPSEEK_MODEL.lower()
GOOGLE_DOCS_ENABLED = os.getenv("GOOGLE_DOCS_ENABLED", "true").lower() not in {"0", "false", "no"}
GOOGLE_DOCS_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_DOCS_CREDENTIALS_PATH",
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(backend_dir, "credential", "key.json"))
)
GOOGLE_DOCS_CREDENTIALS_JSON = os.getenv("GOOGLE_DOCS_CREDENTIALS_JSON")
VOICE_DOC_MAX_CHARS = int(os.getenv("VOICE_DOC_MAX_CHARS", "800000"))
STORAGE_MODE = os.getenv("STORAGE_MODE", "google_doc")
INDEX_MODE = os.getenv("INDEX_MODE", "sqlite")
GOOGLE_DOCS_DEFAULT_DOC_ID = os.getenv("GOOGLE_DOCS_DEFAULT_DOC_ID")
FIRESTORE_ENABLED = os.getenv("FIRESTORE_ENABLED", "true").lower() in {"1", "true", "yes"}
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID")
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "records")


def resolve_folders_config_path() -> str:
    explicit_path = os.getenv("FOLDERS_CONFIG_PATH")
    if explicit_path:
        return explicit_path

    candidates = [
        os.path.join(root_dir, "folders.json"),
        os.path.join(backend_dir, "folders.json"),
        os.path.join(os.getcwd(), "folders.json"),
    ]
    return next((path for path in candidates if os.path.exists(path)), candidates[0])


FOLDERS_CONFIG_PATH = resolve_folders_config_path()

class ParseRequest(BaseModel):
    text: str


class WikiEntryRequest(BaseModel):
    title: str
    body: str
    topic: str = "personal_playbook"
    tags: list[str] = []
    source: str = "manual"
    confidence: str | None = None


class MemoryAskRequest(BaseModel):
    query: str
    types: list[str] = ["wiki", "journal"]
    limit: int = 8


class RecordCategoryUpdateRequest(BaseModel):
    category: str


class RecordCreateRequest(BaseModel):
    text: str
    title: str | None = None
    summary: str | None = None
    category: str = "inbox"
    source: str = "text"


class RecordUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    cleaned_text: str | None = None
    category: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_voice_db() -> None:
    os.makedirs(os.path.dirname(VOICE_DB_PATH), exist_ok=True)
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_entries (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                folder_id TEXT NOT NULL,
                prompt_id TEXT,
                transcript TEXT NOT NULL,
                audio_uri TEXT,
                source_filename TEXT,
                mime_type TEXT,
                duration_ms INTEGER,
                parsed_task_json TEXT,
                google_doc_id TEXT,
                google_doc_url TEXT,
                google_doc_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(voice_entries)").fetchall()}
        migrations = {
            "google_doc_id": "ALTER TABLE voice_entries ADD COLUMN google_doc_id TEXT",
            "google_doc_url": "ALTER TABLE voice_entries ADD COLUMN google_doc_url TEXT",
            "google_doc_status": "ALTER TABLE voice_entries ADD COLUMN google_doc_status TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wiki_entries (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                topic TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    source_type,
                    source_id,
                    title,
                    body,
                    tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError as e:
            logger.warning(f"[Memory] SQLite FTS5 unavailable; LIKE search fallback will be used: {e}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_transcript TEXT NOT NULL,
                cleaned_text TEXT NOT NULL,
                category TEXT NOT NULL,
                category_label TEXT NOT NULL,
                confidence REAL NOT NULL,
                needs_review INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                storage_status_json TEXT NOT NULL,
                folder_id TEXT,
                mode TEXT,
                prompt_id TEXT,
                google_doc_id TEXT,
                google_doc_url TEXT,
                google_doc_status TEXT
            )
            """
        )
        conn.commit()


def load_voice_folders() -> dict:
    default_config = {
        "folders": [
            {
                "id": "LifeVoice",
                "name": "Life Voice",
                "description": "Personal daily recordings",
                "default": True,
                "gdrive_folder_id": ""
            }
        ]
    }
    if not os.path.exists(FOLDERS_CONFIG_PATH):
        return default_config
    try:
        with open(FOLDERS_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("folders"), list):
            return default_config
        return data
    except Exception as e:
        logger.error(f"[Voice] Failed to load folders.json: {e}")
        return default_config


def validate_folder_id(folder_id: str) -> str:
    folders = load_voice_folders().get("folders", [])
    valid_ids = {folder.get("id") for folder in folders}
    if folder_id not in valid_ids:
        default_folder = next((f for f in folders if f.get("default")), folders[0] if folders else {"id": "LifeVoice"})
        return default_folder.get("id", "LifeVoice")
    return folder_id


def get_voice_folder(folder_id: str) -> dict:
    folders = load_voice_folders().get("folders", [])
    return next((folder for folder in folders if folder.get("id") == folder_id), {})


async def transcribe_audio_file(temp_file_path: str) -> str:
    if not openai_key:
        raise HTTPException(status_code=401, detail="Backend is missing OPENAI_API_KEY.")
    try:
        with open(temp_file_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model=VOICE_TRANSCRIBE_MODEL,
                file=audio_file,
                language="zh"
            )
        transcript = getattr(transcription, "text", "") or ""
        if not transcript.strip():
            raise HTTPException(status_code=422, detail="No speech was detected in the uploaded audio.")
        return transcript.strip()
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        logger.error(f"[Voice] Transcription failed: {err_str}")
        if "insufficient_quota" in err_str or "429" in err_str:
            raise HTTPException(status_code=402, detail="OpenAI quota is insufficient for audio transcription.")
        raise HTTPException(status_code=500, detail=f"Audio transcription failed: {err_str}")


def upload_audio_to_gcs(file_path: str, entry_id: str, folder_id: str, filename: str, content_type: str | None) -> str:
    if not GCS_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="GCS_BUCKET_NAME is required before audio uploads can be stored.")
    if storage is None:
        raise HTTPException(status_code=500, detail="google-cloud-storage is not installed.")
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        ext = os.path.splitext(filename)[1] or ".webm"
        blob_name = f"voice/{folder_id}/{entry_id}{ext}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(file_path, content_type=content_type or "application/octet-stream")
        return f"gs://{GCS_BUCKET_NAME}/{blob_name}"
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Voice] GCS upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")


def resolve_google_docs_credentials_path() -> str | None:
    candidates = [
        GOOGLE_DOCS_CREDENTIALS_PATH,
        os.path.join(backend_dir, "credential", "key.json"),
        os.path.join(os.path.dirname(root_dir), "voice_recorder", "backend", "credential", "key.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def parse_google_docs_credentials_json() -> dict | None:
    if not GOOGLE_DOCS_CREDENTIALS_JSON:
        return None
    raw = GOOGLE_DOCS_CREDENTIALS_JSON.strip()
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception as e:
        logger.error(f"[Voice] Failed to parse GOOGLE_DOCS_CREDENTIALS_JSON: {e}")
        return None


def get_google_credential_email(creds: object | None) -> str | None:
    if creds is None:
        return None
    return (
        getattr(creds, "service_account_email", None)
        or getattr(creds, "_service_account_email", None)
        or getattr(creds, "signer_email", None)
    )


def resolve_google_docs_credentials() -> tuple[object | None, str, str | None]:
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/datastore",
        "https://www.googleapis.com/auth/cloud-platform",
    ]

    credentials_info = parse_google_docs_credentials_json()
    if credentials_info:
        if service_account is None:
            raise RuntimeError("google-api-python-client and google-auth are required for Google Docs sync.")
        creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=scopes)
        return creds, "service_account_json", get_google_credential_email(creds)

    credentials_path = resolve_google_docs_credentials_path()
    if credentials_path:
        if service_account is None:
            raise RuntimeError("google-api-python-client and google-auth are required for Google Docs sync.")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        return creds, f"service_account_file:{credentials_path}", get_google_credential_email(creds)

    if google_auth is not None:
        try:
            creds, _ = google_auth.default(scopes=scopes)
            if creds is not None:
                return creds, "application_default_credentials", get_google_credential_email(creds)
        except Exception as e:
            logger.warning(f"[Voice] Google ADC unavailable: {e}")

    return None, "none", None


# Initialize Firestore Repository if enabled
firestore_repo = None
if FIRESTORE_ENABLED:
    try:
        from repositories.firestore_repository import FirestoreRepository
        creds, auth_mode, auth_email = resolve_google_docs_credentials()
        firestore_repo = FirestoreRepository(
            credentials=creds,
            project_id=FIRESTORE_PROJECT_ID or getattr(creds, "project_id", None),
            collection_name=FIRESTORE_COLLECTION
        )
        logger.info(f"Successfully initialized FirestoreRepository with auth mode: {auth_mode}")
    except Exception as e:
        logger.error(f"Failed to initialize FirestoreRepository: {e}")
        FIRESTORE_ENABLED = False



class GoogleDocAppender:
    def __init__(self, creds: object):
        if build is None:
            raise RuntimeError("google-api-python-client and google-auth are required for Google Docs sync.")
        self.creds = creds
        self.drive_service = build("drive", "v3", credentials=self.creds, cache_discovery=False)
        self.docs_service = build("docs", "v1", credentials=self.creds, cache_discovery=False)

    def find_doc_by_name(self, drive_folder_id: str, doc_name: str) -> str | None:
        safe_name = doc_name.replace("'", "\\'")
        query = (
            f"name='{safe_name}' and '{drive_folder_id}' in parents and trashed=false and "
            "mimeType='application/vnd.google-apps.document'"
        )
        result = self.drive_service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def create_doc(self, drive_folder_id: str, doc_name: str) -> str:
        doc = self.drive_service.files().create(
            body={
                "name": doc_name,
                "parents": [drive_folder_id],
                "mimeType": "application/vnd.google-apps.document",
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        return doc["id"]

    def get_doc_size(self, doc_id: str) -> int:
        doc = self.docs_service.documents().get(
            documentId=doc_id,
            fields="body(content(endIndex))",
        ).execute()
        content = doc.get("body", {}).get("content", [])
        return content[-1].get("endIndex", 1) if content else 1

    def append_text(self, doc_id: str, text: str) -> None:
        doc = self.docs_service.documents().get(
            documentId=doc_id,
            fields="revisionId,body(content(endIndex))",
        ).execute()
        content = doc.get("body", {}).get("content", [])
        end_index = content[-1].get("endIndex", 1) - 1 if content else 1
        body = {
            "requests": [{
                "insertText": {
                    "text": text,
                    "location": {"index": end_index},
                }
            }]
        }
        revision_id = doc.get("revisionId")
        if revision_id:
            body["writeControl"] = {"targetRevisionId": revision_id}
        self.docs_service.documents().batchUpdate(documentId=doc_id, body=body).execute()


def format_google_doc_entry(entry: dict, folder: dict) -> str:
    folder_name = folder.get("name") or entry["folder_id"]
    return f"[{entry['created_at']}] {folder_name} - {entry['transcript']}\n\n"


def format_record_for_google_doc(record: Record, folder: dict) -> str:
    tags = record.metadata.tags or []
    tag_text = " / ".join(tags) if tags else "no tags"
    created = record.created_at.strftime("%Y-%m-%d %H:%M")
    return (
        f"\n## {created} · {record.category_label} · {tag_text}\n\n"
        f"{record.cleaned_text}\n\n"
        f"AI Summary: {record.summary}\n\n"
        f"Record ID:\n{record.id}\n\n"
    )


def build_google_doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def classify_google_doc_error(error: Exception) -> str:
    err = str(error)
    lowered = err.lower()
    if "docs api has not been used" in lowered or "docs.googleapis.com" in lowered and "accessnotconfigured" in lowered:
        return "failed:google_docs_api_disabled"
    if "drive api has not been used" in lowered or "drive.googleapis.com" in lowered and "accessnotconfigured" in lowered:
        return "failed:google_drive_api_disabled"
    if "the caller does not have permission" in lowered or "permission_denied" in lowered or "insufficient permission" in lowered:
        return "failed:permission_denied_share_doc"
    if "requested entity was not found" in lowered or "not found" in lowered:
        return "failed:doc_not_found_or_not_shared"
    if "invalid_grant" in lowered:
        return "failed:invalid_google_credentials"
    return f"failed:{err[:180]}"


def append_journal_to_google_doc(entry: dict) -> dict:
    if not GOOGLE_DOCS_ENABLED:
        return {"status": "disabled", "doc_id": None, "doc_url": None}

    folder = get_voice_folder(entry["folder_id"])
    configured_doc_id = folder.get("google_doc_id")
    drive_folder_id = folder.get("gdrive_folder_id")
    if not configured_doc_id and not drive_folder_id:
        return {"status": "skipped:no_gdrive_folder_id", "doc_id": None, "doc_url": None}

    creds, auth_mode, auth_email = resolve_google_docs_credentials()
    if not creds:
        return {"status": "skipped:no_google_credentials", "doc_id": None, "doc_url": None}

    try:
        logger.info(f"[Voice] Google Docs auth mode: {auth_mode}; email: {auth_email or 'unknown'}")
        appender = GoogleDocAppender(creds)
        if configured_doc_id:
            doc_id = configured_doc_id
        else:
            folder_name = folder.get("name") or entry["folder_id"]
            volume = 1
            while True:
                doc_name = f"{folder_name} Transcripts - Vol {volume}"
                doc_id = appender.find_doc_by_name(drive_folder_id, doc_name)
                if not doc_id:
                    doc_id = appender.create_doc(drive_folder_id, doc_name)
                    break
                if appender.get_doc_size(doc_id) < VOICE_DOC_MAX_CHARS:
                    break
                volume += 1

        appender.append_text(doc_id, format_google_doc_entry(entry, folder))
        return {
            "status": "synced",
            "doc_id": doc_id,
            "doc_url": build_google_doc_url(doc_id),
        }
    except Exception as e:
        logger.error(f"[Voice] Google Doc append failed: {e}")
        return {"status": classify_google_doc_error(e), "doc_id": None, "doc_url": None}


def append_record_to_google_doc(record: Record, folder_id: str) -> dict:
    if STORAGE_MODE != "google_doc":
        return {"backend": "google_doc", "status": "skipped:storage_mode_not_google_doc", "doc_id": None, "doc_url": None}
    if not GOOGLE_DOCS_ENABLED:
        return {"backend": "google_doc", "status": "disabled", "doc_id": None, "doc_url": None}

    folder = get_voice_folder(folder_id)
    configured_doc_id = folder.get("google_doc_id") or GOOGLE_DOCS_DEFAULT_DOC_ID
    drive_folder_id = folder.get("gdrive_folder_id")
    if not configured_doc_id and not drive_folder_id:
        return {"backend": "google_doc", "status": "skipped:no_gdrive_folder_id", "doc_id": None, "doc_url": None}

    creds, auth_mode, auth_email = resolve_google_docs_credentials()
    if not creds:
        return {"backend": "google_doc", "status": "skipped:no_google_credentials", "doc_id": None, "doc_url": None}

    try:
        logger.info(f"[Record] Google Docs auth mode: {auth_mode}; email: {auth_email or 'unknown'}")
        appender = GoogleDocAppender(creds)
        if configured_doc_id:
            doc_id = configured_doc_id
        else:
            folder_name = folder.get("name") or folder_id
            volume = 1
            while True:
                doc_name = f"{folder_name} Records - Vol {volume}"
                doc_id = appender.find_doc_by_name(drive_folder_id, doc_name)
                if not doc_id:
                    doc_id = appender.create_doc(drive_folder_id, doc_name)
                    break
                if appender.get_doc_size(doc_id) < VOICE_DOC_MAX_CHARS:
                    break
                volume += 1

        appender.append_text(doc_id, format_record_for_google_doc(record, folder))
        return {
            "backend": "google_doc",
            "status": "synced",
            "doc_id": doc_id,
            "doc_url": build_google_doc_url(doc_id),
        }
    except Exception as e:
        logger.error(f"[Record] Google Doc append failed: {e}")
        return {"backend": "google_doc", "status": classify_google_doc_error(e), "doc_id": None, "doc_url": None}


def insert_voice_entry(entry: dict) -> None:
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO voice_entries (
                id, mode, folder_id, prompt_id, transcript, audio_uri,
                source_filename, mime_type, duration_ms, parsed_task_json,
                google_doc_id, google_doc_url, google_doc_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["mode"],
                entry["folder_id"],
                entry.get("prompt_id"),
                entry["transcript"],
                entry.get("audio_uri"),
                entry.get("source_filename"),
                entry.get("mime_type"),
                entry.get("duration_ms"),
                json.dumps(entry.get("parsed_task"), ensure_ascii=False) if entry.get("parsed_task") else None,
                entry.get("google_doc_id"),
                entry.get("google_doc_url"),
                entry.get("google_doc_status"),
                entry["created_at"],
                entry["updated_at"],
            ),
        )
        conn.commit()
    if entry.get("mode") == "journal":
        index_memory_item("journal", entry["id"], entry.get("folder_id", "Journal"), entry.get("transcript", ""))


def list_voice_entries(folder_id: str | None, mode: str | None, limit: int) -> list[dict]:
    params = []
    where = ""
    clauses = []
    if folder_id:
        clauses.append("folder_id = ?")
        params.append(folder_id)
    if mode and mode != "all":
        clauses.append("mode = ?")
        params.append(mode)
    if clauses:
        where = f"WHERE {' AND '.join(clauses)}"
    params.append(limit)
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, mode, folder_id, prompt_id, transcript, audio_uri,
                   source_filename, mime_type, duration_ms, parsed_task_json,
                   google_doc_id, google_doc_url, google_doc_status,
                   created_at, updated_at
            FROM voice_entries
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        parsed_task_json = item.pop("parsed_task_json", None)
        item["parsed_task"] = json.loads(parsed_task_json) if parsed_task_json else None
        entries.append(item)
    return entries


def record_to_public_dict(record: Record) -> dict:
    data = record.model_dump(mode="json")
    data["tags"] = record.metadata.tags
    return data


def build_record_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"rec_{timestamp}_{uuid.uuid4().hex[:8]}"


def mode_to_record_category(mode: str, transcript: str, route: dict | None = None) -> str:
    if mode == "wiki":
        return "life_knowledge"
    if mode == "ask":
        return "ask"
    if mode == "schedule":
        return "family_plan"
    lowered = (transcript or "").lower()
    if re.search(r"(work|project|code|coding|meeting|dashboard|瀛︿範|宸ヤ綔|浠ｇ爜|椤圭洰|浼氳)", lowered):
        return "work_idea"
    return "self_reflection"


def normalize_record_category(category: str | None) -> str:
    return category if category in CATEGORY_LABELS else "inbox"


def simple_tags_from_text(text: str, limit: int = 6) -> list[str]:
    tags = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = token.lower()
        if normalized not in tags:
            tags.append(normalized)
        if len(tags) >= limit:
            break
    return tags


async def create_record_draft(transcript: str, mode: str, source: str, route: dict | None = None) -> dict:
    fallback_category = mode_to_record_category(mode, transcript, route)
    fallback = {
        "category": fallback_category,
        "category_label": CATEGORY_LABELS[fallback_category],
        "confidence": float(route.get("confidence", 0.7)) if route else 0.7,
        "needs_review": False,
        "title": (transcript.strip().splitlines()[0][:80] or "Voice Record"),
        "summary": transcript.strip()[:180],
        "cleaned_text": transcript.strip(),
        "tags": simple_tags_from_text(transcript),
        "people": [],
        "places": [],
        "time_expression": None,
        "action_required": mode == "schedule",
        "calendar_candidate": mode == "schedule",
    }
    if not DEEPSEEK_API_KEY:
        return fallback

    prompt = {
        "task": "Create a structured Record draft from this personal voice/text input.",
        "allowed_categories": list(CATEGORY_LABELS.keys()),
        "mode_hint": mode,
        "text": transcript,
        "return_json_schema": {
            "category": "one allowed category",
            "category_label": "human readable label",
            "confidence": 0.0,
            "needs_review": False,
            "title": "short title",
            "summary": "short summary",
            "cleaned_text": "lightly cleaned original text",
            "tags": ["short tags"],
            "people": [],
            "places": [],
            "time_expression": None,
            "action_required": False,
            "calendar_candidate": False,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as deepseek_client:
            response = await deepseek_client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": "Return only valid JSON. Classify the note into the allowed Record category list."},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
        if response.status_code >= 400:
            logger.warning(f"[Record] DeepSeek draft failed; using fallback: {response.text[:300]}")
            return fallback
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
        draft = json.loads(content)
        category = normalize_record_category(draft.get("category"))
        draft["category"] = category
        draft["category_label"] = draft.get("category_label") or CATEGORY_LABELS[category]
        draft["confidence"] = max(0.0, min(1.0, float(draft.get("confidence", fallback["confidence"]))))
        draft["needs_review"] = bool(draft.get("needs_review", False))
        draft["title"] = (draft.get("title") or fallback["title"])[:120]
        draft["summary"] = draft.get("summary") or fallback["summary"]
        draft["cleaned_text"] = draft.get("cleaned_text") or fallback["cleaned_text"]
        draft["tags"] = draft.get("tags") if isinstance(draft.get("tags"), list) else fallback["tags"]
        draft["people"] = draft.get("people") if isinstance(draft.get("people"), list) else []
        draft["places"] = draft.get("places") if isinstance(draft.get("places"), list) else []
        draft["time_expression"] = draft.get("time_expression")
        draft["action_required"] = bool(draft.get("action_required", mode == "schedule"))
        draft["calendar_candidate"] = bool(draft.get("calendar_candidate", mode == "schedule"))
        return draft
    except Exception as e:
        logger.warning(f"[Record] DeepSeek draft exception; using fallback: {e}")
        return fallback


def build_record_from_draft(
    draft: dict,
    transcript: str,
    source: str,
    now: str,
    mode: str,
    storage_status: dict | None = None,
) -> Record:
    category = normalize_record_category(draft.get("category"))
    metadata = RecordMetadata(
        people=draft.get("people") or [],
        places=draft.get("places") or [],
        tags=draft.get("tags") or [],
        time_expression=draft.get("time_expression"),
        action_required=bool(draft.get("action_required", mode == "schedule")),
        calendar_candidate=bool(draft.get("calendar_candidate", mode == "schedule")),
    )
    return Record(
        id=build_record_id(),
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
        source=source,
        raw_transcript=transcript,
        cleaned_text=draft.get("cleaned_text") or transcript,
        category=category,
        category_label=draft.get("category_label") or CATEGORY_LABELS[category],
        confidence=float(draft.get("confidence", 0.7)),
        needs_review=bool(draft.get("needs_review", False)),
        title=draft.get("title") or transcript[:80] or "Voice Record",
        summary=draft.get("summary") or transcript[:180],
        metadata=metadata,
        storage_status=storage_status or {},
    )


def insert_record(record: Record, folder_id: str, mode: str, prompt_id: str | None) -> dict:
    status = record.storage_status or {}
    primary = status.get("primary") or {}
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO records (
                id, created_at, updated_at, source, raw_transcript, cleaned_text,
                category, category_label, confidence, needs_review, title, summary,
                metadata_json, storage_status_json, folder_id, mode, prompt_id,
                google_doc_id, google_doc_url, google_doc_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.source,
                record.raw_transcript,
                record.cleaned_text,
                record.category,
                record.category_label,
                record.confidence,
                1 if record.needs_review else 0,
                record.title,
                record.summary,
                json.dumps(record.metadata.model_dump(), ensure_ascii=False),
                json.dumps(record.storage_status, ensure_ascii=False),
                folder_id,
                mode,
                prompt_id,
                primary.get("doc_id"),
                primary.get("doc_url"),
                primary.get("status"),
            ),
        )
        conn.commit()
    index_memory_item("record", record.id, record.title, f"{record.summary}\n{record.cleaned_text}")
    return {"backend": "sqlite", "status": "saved"}


def row_to_record_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    metadata = json.loads(item.pop("metadata_json") or "{}")
    storage_status = json.loads(item.pop("storage_status_json") or "{}")
    item["metadata"] = metadata
    item["storage_status"] = storage_status
    item["tags"] = metadata.get("tags", [])
    return item


def list_records(category: str | None, limit: int, q: str | None = None) -> list[dict]:
    params = []
    clause = ""
    filters = []
    if category and category != "all":
        filters.append("(category = ? OR mode = ?)")
        params.extend([category, category])
    if q:
        filters.append("(title LIKE ? OR summary LIKE ? OR cleaned_text LIKE ? OR raw_transcript LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if filters:
        clause = "WHERE " + " AND ".join(filters)
    params.append(limit)
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM records
            {clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [row_to_record_dict(row) for row in rows]


def update_record(record_id: str, updates: dict) -> dict:
    allowed = {
        "title",
        "summary",
        "cleaned_text",
        "raw_transcript",
        "category",
        "category_label",
    }
    payload = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if not payload:
        return {"ok": True, "record_id": record_id, "status": "skipped:no_updates"}
    payload["updated_at"] = utc_now_iso()
    columns = ", ".join(f"{key} = ?" for key in payload)
    values = list(payload.values())
    values.append(record_id)
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        result = conn.execute(
            f"UPDATE records SET {columns} WHERE id = ?",
            values,
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"ok": True, "record_id": record_id, "status": "updated"}


def delete_record(record_id: str) -> dict:
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        result = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"ok": True, "record_id": record_id, "status": "deleted"}


def update_record_category(record_id: str, category: str) -> dict:
    category = normalize_record_category(category)
    label = CATEGORY_LABELS[category]
    update_record(record_id, {"category": category, "category_label": label})
    return {"ok": True, "record_id": record_id, "category": category, "category_label": label}


async def list_records_any(category: str | None, limit: int, q: str | None = None) -> tuple[list[dict], str]:
    if FIRESTORE_ENABLED and firestore_repo:
        try:
            if q:
                records = await firestore_repo.search_records(q, category=category, limit=limit)
            else:
                records = await firestore_repo.list_records(category=category, limit=limit)
            return [record_to_public_dict(record) for record in records], "firestore"
        except Exception as e:
            logger.error(f"[Records] Firestore list/search failed, falling back to SQLite: {e}")
    return list_records(category, limit, q), "sqlite"


async def save_record_any(record: Record, folder_id: str = "LifeVoice", mode: str = "manual") -> dict:
    storage_status = {}
    if FIRESTORE_ENABLED and firestore_repo:
        try:
            storage_status["firestore"] = await firestore_repo.save_record(record)
        except Exception as e:
            logger.error(f"[Records] Firestore save failed: {e}")
            storage_status["firestore"] = {"backend": "firestore", "status": f"failed:{e}"}
    storage_status["sqlite"] = insert_record(record, folder_id, mode, None)
    return storage_status


async def update_record_any(record_id: str, req: RecordUpdateRequest) -> dict:
    updates = {}
    if req.title is not None:
        updates["title"] = req.title.strip()
    if req.summary is not None:
        updates["summary"] = req.summary.strip()
    if req.cleaned_text is not None:
        cleaned = req.cleaned_text.strip()
        updates["cleaned_text"] = cleaned
        updates["raw_transcript"] = cleaned
        if "summary" not in updates:
            updates["summary"] = cleaned[:180]
    if req.category is not None:
        category = normalize_record_category(req.category)
        updates["category"] = category
        updates["category_label"] = CATEGORY_LABELS[category]

    results = {}
    firestore_updated = False
    if FIRESTORE_ENABLED and firestore_repo:
        try:
            results["firestore"] = await firestore_repo.update_record(record_id, updates)
            firestore_updated = True
        except Exception as e:
            logger.error(f"[Records] Firestore update failed: {e}")
            results["firestore"] = {"backend": "firestore", "status": f"failed:{e}"}
    try:
        results["sqlite"] = update_record(record_id, updates)
    except HTTPException:
        if not firestore_updated:
            raise
        results["sqlite"] = {"backend": "sqlite", "status": "skipped:not_found"}
    return {"ok": True, "record_id": record_id, "results": results}


async def delete_record_any(record_id: str) -> dict:
    results = {}
    firestore_deleted = False
    if FIRESTORE_ENABLED and firestore_repo:
        try:
            results["firestore"] = await firestore_repo.delete_record(record_id)
            firestore_deleted = True
        except Exception as e:
            logger.error(f"[Records] Firestore delete failed: {e}")
            results["firestore"] = {"backend": "firestore", "status": f"failed:{e}"}
    try:
        results["sqlite"] = delete_record(record_id)
    except HTTPException:
        if not firestore_deleted:
            raise
        results["sqlite"] = {"backend": "sqlite", "status": "skipped:not_found"}
    return {"ok": True, "record_id": record_id, "results": results}


async def extract_submission_text(
    file: UploadFile | None,
    text: str | None,
    entry_id: str,
    folder_id: str,
) -> tuple[str, str | None, str | None, str | None]:
    transcript = (text or "").strip()
    audio_uri = None
    source_filename = None
    mime_type = None
    temp_file_path = None

    if file is not None:
        source_filename = file.filename or "recording.webm"
        mime_type = file.content_type or "application/octet-stream"
        ext = os.path.splitext(source_filename)[1] or ".webm"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
                contents = await file.read()
                if not contents:
                    raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
                temp_file.write(contents)
                temp_file_path = temp_file.name

            if GCS_BUCKET_NAME:
                audio_uri = upload_audio_to_gcs(temp_file_path, entry_id, folder_id, source_filename, mime_type)
            else:
                logger.warning("[Voice] GCS_BUCKET_NAME is not configured; skipping raw audio upload for local development.")
            transcript = await transcribe_audio_file(temp_file_path)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as ex:
                    logger.error(f"[Voice] Failed to remove temp file: {ex}")

    if not transcript:
        raise HTTPException(status_code=400, detail="Provide either a non-empty text field or an audio file.")
    return transcript, audio_uri, source_filename, mime_type


WIKI_TOPICS = [
    "places_local_life",
    "home_admin",
    "personal_playbook",
    "health_body",
    "people_relationships",
    "work_learning",
]


def normalize_memory_types(types: list[str] | str | None) -> set[str]:
    if isinstance(types, str):
        raw_types = [item.strip() for item in types.split(",")]
    else:
        raw_types = types or ["wiki", "journal"]
    allowed = {"wiki", "journal", "record", "records"}
    selected = {item for item in raw_types if item in allowed}
    return selected or allowed


def index_memory_item(source_type: str, source_id: str, title: str, body: str) -> None:
    try:
        with sqlite3.connect(VOICE_DB_PATH) as conn:
            conn.execute("DELETE FROM memory_fts WHERE source_type = ? AND source_id = ?", (source_type, source_id))
            conn.execute(
                "INSERT INTO memory_fts (source_type, source_id, title, body) VALUES (?, ?, ?, ?)",
                (source_type, source_id, title, body),
            )
            conn.commit()
    except sqlite3.OperationalError as e:
        logger.warning(f"[Memory] Failed to update FTS index; continuing without FTS: {e}")


def insert_wiki_entry(entry: dict) -> None:
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO wiki_entries (
                id, title, body, topic, tags_json, source, confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["title"],
                entry["body"],
                entry["topic"],
                json.dumps(entry.get("tags", []), ensure_ascii=False),
                entry.get("source", "voice"),
                entry.get("confidence"),
                entry["created_at"],
                entry["updated_at"],
            ),
        )
        conn.commit()
    index_memory_item("wiki", entry["id"], entry["title"], entry["body"])


def list_wiki_entries(topic: str | None, q: str | None, limit: int) -> list[dict]:
    where = []
    params = []
    if topic:
        where.append("topic = ?")
        params.append(topic)
    if q:
        where.append("(title LIKE ? OR body LIKE ? OR tags_json LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    params.append(limit)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, title, body, topic, tags_json, source, confidence, created_at, updated_at
            FROM wiki_entries
            {clause}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json") or "[]")
        entries.append(item)
    return entries


def parse_temporal_expression(query: str, current_time: datetime) -> tuple[datetime, datetime] | None:
    from datetime import timedelta
    try:
        local_now = current_time.astimezone()
        local_tz = local_now.tzinfo
    except Exception:
        local_tz = None

    def day_range(day: datetime):
        start_local = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        if local_tz:
            if start_local.tzinfo is None:
                start_local = start_local.replace(tzinfo=local_tz)
            if end_local.tzinfo is None:
                end_local = end_local.replace(tzinfo=local_tz)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    query_lower = query.lower()
    
    if "昨天" in query or "yesterday" in query_lower:
        yesterday = current_time - timedelta(days=1)
        return day_range(yesterday)
        
    if "今天" in query or "today" in query_lower:
        return day_range(current_time)
        
    if "前天" in query:
        day_before = current_time - timedelta(days=2)
        return day_range(day_before)

    if "大前天" in query:
        three_days_ago = current_time - timedelta(days=3)
        return day_range(three_days_ago)

    if "上周" in query or "last week" in query_lower:
        days_to_last_monday = current_time.weekday() + 7
        last_monday = current_time - timedelta(days=days_to_last_monday)
        last_sunday = last_monday + timedelta(days=6)
        start_local = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
        if local_tz:
            start_local = start_local.replace(tzinfo=local_tz)
            end_local = end_local.replace(tzinfo=local_tz)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    if "这周" in query or "本周" in query or "this week" in query_lower:
        days_to_monday = current_time.weekday()
        monday = current_time - timedelta(days=days_to_monday)
        start_local = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = current_time.replace(hour=23, minute=59, second=59, microsecond=999999)
        if local_tz:
            start_local = start_local.replace(tzinfo=local_tz)
            end_local = end_local.replace(tzinfo=local_tz)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    if "最近" in query or "这几天" in query or "recent" in query_lower:
        start_local = (current_time - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = current_time.replace(hour=23, minute=59, second=59, microsecond=999999)
        if local_tz:
            start_local = start_local.replace(tzinfo=local_tz)
            end_local = end_local.replace(tzinfo=local_tz)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    match = re.search(r"(\d+|[一二两三四五六七八九十百]+)\s*天前", query)
    if match:
        num_str = match.group(1)
        num = parse_chinese_number(num_str) if not num_str.isdigit() else int(num_str)
        if num is not None:
            target_day = current_time - timedelta(days=num)
            return day_range(target_day)

    return None


async def search_memory(query: str, types: list[str] | str | None = None, limit: int = 8) -> list[dict]:
    query = (query or "").strip()
    selected_types = normalize_memory_types(types)
    if not query:
        return []

    # Detect if user query contains temporal expression for Date-Range filtering (Scheme A)
    date_range = parse_temporal_expression(query, datetime.now().astimezone())
    if date_range:
        start_date, end_date = date_range
        logger.info(f"[Temporal Query] Detected date range: {start_date} to {end_date} (UTC)")
        
        category_filter = []
        if "wiki" in selected_types:
            category_filter.append("life_knowledge")
        if "journal" in selected_types:
            category_filter.extend(["self_reflection", "work_idea", "family_plan", "inbox"])
            
        results = []
        
        # 1. Query Firestore for records in date range
        if FIRESTORE_ENABLED and firestore_repo:
            try:
                logger.info(f"[Firestore Search] Fetching records within date range: {start_date} to {end_date}")
                records = await firestore_repo.list_records_in_date_range(start_date, end_date, limit=limit * 2)
                
                # Filter by category in memory
                if category_filter:
                    records = [r for r in records if r.category in category_filter]
                    
                for r in records:
                    created_str = r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)
                    results.append({
                        "type": r.category,
                        "id": r.id,
                        "record_id": r.id,
                        "title": r.title,
                        "category_label": r.category_label,
                        "created_at": created_str,
                        "snippet": (r.summary or r.cleaned_text or "")[:500]
                    })
                logger.info(f"[Firestore Search] Date-range query succeeded, found {len(results)} matches.")
            except Exception as fe:
                logger.error(f"[Firestore Search] Date-range query failed: {fe}. Falling back to SQLite.")
                
        # 2. SQLite Fallback query for records in date range
        if not results:
            try:
                start_iso = start_date.isoformat()
                end_iso = end_date.isoformat()
                category_clause = ""
                params = [start_iso, end_iso]
                if category_filter:
                    placeholders = ",".join("?" for _ in category_filter)
                    category_clause = f"AND category IN ({placeholders})"
                    params.extend(category_filter)
                params.append(limit)
                
                with sqlite3.connect(VOICE_DB_PATH) as conn:
                    conn.row_factory = sqlite3.Row
                    record_rows = conn.execute(
                        f"""
                        SELECT id, category, category_label, title, summary, cleaned_text, created_at
                        FROM records
                        WHERE (created_at >= ? AND created_at <= ?)
                        {category_clause}
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()
                    
                    for row in record_rows:
                        results.append({
                            "type": row["category"],
                            "id": row["id"],
                            "record_id": row["id"],
                            "title": row["title"],
                            "category_label": row["category_label"],
                            "created_at": row["created_at"],
                            "snippet": (row["summary"] or row["cleaned_text"] or "")[:500]
                        })
                logger.info(f"[SQLite Search] Date-range query succeeded, found {len(results)} matches.")
            except Exception as se:
                logger.error(f"[SQLite Search] Date-range query failed: {se}")
                
        if results:
            return results[:limit]
        else:
            logger.info(f"[Temporal Query] No records found within {start_date} and {end_date}.")
            return []
    selected_types = normalize_memory_types(types)
    if not query:
        return []

    # 1. Firestore Search if enabled
    if FIRESTORE_ENABLED and firestore_repo:
        try:
            logger.info(f"[Firestore Search] Starting vector search query for: '{query}'")
            category_filter = []
            if "wiki" in selected_types:
                category_filter.append("life_knowledge")
            if "journal" in selected_types:
                category_filter.extend(["self_reflection", "work_idea", "family_plan", "inbox"])
            if "record" in selected_types or "records" in selected_types:
                category_filter = []
                
            query_embedding = await get_text_embedding(query)
            if query_embedding:
                try:
                    records = await firestore_repo.search_vector_nearest(
                        query_embedding=query_embedding,
                        category_filter=category_filter or None,
                        limit=limit
                    )
                    results = []
                    for r in records:
                        created_str = r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)
                        results.append({
                            "type": r.category,
                            "id": r.id,
                            "record_id": r.id,
                            "title": r.title,
                            "category_label": r.category_label,
                            "created_at": created_str,
                            "snippet": (r.summary or r.cleaned_text or "")[:500]
                        })
                    logger.info(f"[Firestore Search] Vector search succeeded, found {len(results)} matches.")
                    return results
                except Exception as ve_err:
                    err_str = str(ve_err)
                    if "FAILED_PRECONDITION" in err_str or "index" in err_str.lower():
                        logger.warning(
                            f"[Firestore Search] Vector Index not found. "
                            f"Please create a Vector Index for 'embedding' in Firebase Console! "
                            f"Falling back to high-precision local scanning. Error: {ve_err}"
                        )
                    else:
                        logger.error(f"[Firestore Search] Vector search exception: {ve_err}. Falling back to local scanning.")
            
            # Local keyword scanning and scoring (Fallback)
            logger.info("[Firestore Search] Executing local keyword scanning fallback...")
            all_records = await firestore_repo.list_records(limit=150)
            if category_filter:
                all_records = [r for r in all_records if r.category in category_filter]
                
            scored_results = []
            keywords = [w.lower() for w in re.findall(r"[\w\u4e00-\u9fff]+", query)]
            
            for r in all_records:
                score = 0
                title_lower = r.title.lower()
                summary_lower = r.summary.lower()
                text_lower = r.cleaned_text.lower()
                
                for kw in keywords:
                    if kw in title_lower:
                        score += 10
                    if kw in summary_lower:
                        score += 5
                    if kw in text_lower:
                        score += 2
                
                for tag in (r.metadata.tags or []):
                    if tag.lower() in keywords:
                        score += 8
                        
                if score > 0:
                    scored_results.append((score, r))
            
            scored_results.sort(key=lambda x: (x[0], x[1].created_at), reverse=True)
            
            results = []
            for score, r in scored_results[:limit]:
                created_str = r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)
                results.append({
                    "type": r.category,
                    "id": r.id,
                    "record_id": r.id,
                    "title": r.title,
                    "category_label": r.category_label,
                    "created_at": created_str,
                    "snippet": (r.summary or r.cleaned_text or "")[:500]
                })
            return results
        except Exception as fe:
            logger.error(f"[Firestore Search] Failed to search Firestore: {fe}. Falling back to SQLite.")

    # 2. SQLite Search fallback
    rows = []
    results = []
    category_filter = []
    if "wiki" in selected_types:
        category_filter.append("life_knowledge")
    if "journal" in selected_types:
        category_filter.extend(["self_reflection", "work_idea", "family_plan", "inbox"])
    if "record" in selected_types or "records" in selected_types:
        category_filter = []

    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        like = f"%{query}%"
        category_clause = ""
        params = [like, like, like]
        if category_filter:
            placeholders = ",".join("?" for _ in category_filter)
            category_clause = f"AND category IN ({placeholders})"
            params.extend(category_filter)
        params.append(limit)
        try:
            record_rows = conn.execute(
                f"""
                SELECT id, category, category_label, title, summary, cleaned_text, created_at
                FROM records
                WHERE (title LIKE ? OR summary LIKE ? OR cleaned_text LIKE ?)
                {category_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            results.extend(
                {
                    "type": row["category"],
                    "id": row["id"],
                    "record_id": row["id"],
                    "title": row["title"],
                    "category_label": row["category_label"],
                    "created_at": row["created_at"],
                    "snippet": (row["summary"] or row["cleaned_text"] or "")[:500],
                }
                for row in record_rows
            )
        except sqlite3.OperationalError as e:
            logger.warning(f"[Memory] records search unavailable; using legacy search: {e}")
    if results:
        return results[:limit]

    try:
        with sqlite3.connect(VOICE_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            fts_query = " OR ".join(re.findall(r"[\w\u4e00-\u9fff]+", query)) or query
            placeholders = ",".join("?" for _ in selected_types)
            rows = conn.execute(
                f"""
                SELECT source_type, source_id, title, body
                FROM memory_fts
                WHERE memory_fts MATCH ? AND source_type IN ({placeholders})
                LIMIT ?
                """,
                [fts_query, *selected_types, limit],
            ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning(f"[Memory] FTS search failed; falling back to LIKE search: {e}")

    results = [
        {
            "type": row["source_type"],
            "id": row["source_id"],
            "title": row["title"],
            "snippet": row["body"][:500],
        }
        for row in rows
    ]
    if results:
        return results

    like = f"%{query}%"
    with sqlite3.connect(VOICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if "wiki" in selected_types:
            for row in conn.execute(
                """
                SELECT id, title, body
                FROM wiki_entries
                WHERE title LIKE ? OR body LIKE ? OR tags_json LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall():
                results.append({"type": "wiki", "id": row["id"], "title": row["title"], "snippet": row["body"][:500]})
        if "journal" in selected_types and len(results) < limit:
            for row in conn.execute(
                """
                SELECT id, folder_id, transcript
                FROM voice_entries
                WHERE mode = 'journal' AND transcript LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, limit - len(results)),
            ).fetchall():
                results.append({"type": "journal", "id": row["id"], "title": row["folder_id"], "snippet": row["transcript"][:500]})

    return results[:limit]


def classify_voice_intent(text: str) -> dict:
    lowered = (text or "").lower()
    if re.search(r"(查|查询|问一下|找一下|有没有|记得吗|what|where|when|search|ask)", lowered):
        return {"intent": "ask", "confidence": 0.85, "reason": "question or lookup phrasing"}
    if re.search(r"(记住|记到|保存到wiki|wiki|知识|小知识|规则|流程|地址|电话|不开门|营业|bank holiday)", lowered):
        return {"intent": "wiki", "confidence": 0.85, "reason": "reusable knowledge phrasing"}
    if re.search(r"(安排|提醒|日程|会议|开会|学习|写|做|下午|上午|晚上|\d{1,2}[:：点]|schedule|calendar)", lowered):
        return {"intent": "schedule", "confidence": 0.8, "reason": "schedule/time phrasing"}
    return {"intent": "journal", "confidence": 0.7, "reason": "default personal note"}


def extract_wiki_entry_from_text(text: str) -> dict:
    tags = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text):
        if len(tags) >= 6:
            break
        normalized = token.lower()
        if normalized not in tags:
            tags.append(normalized)
    topic = "personal_playbook"
    lowered = text.lower()
    if re.search(r"(library|图书馆|超市|医院|gp|车站|colindale|bank holiday|营业|不开门)", lowered):
        topic = "places_local_life"
    elif re.search(r"(保险|账单|签证|银行|税|预约|流程)", lowered):
        topic = "home_admin"
    elif re.search(r"(身体|睡眠|吃药|运动|疼|health)", lowered):
        topic = "health_body"
    elif re.search(r"(工作|学习|代码|项目|会议)", lowered):
        topic = "work_learning"
    title = text.strip().splitlines()[0][:80] or "Life Wiki Note"
    return {
        "title": title,
        "body": text.strip(),
        "topic": topic,
        "tags": tags,
        "source": "voice",
        "confidence": "personal_observation",
    }


async def build_memory_note(query: str) -> tuple[str | None, list[dict]]:
    sources = await search_memory(query, ["wiki", "journal"], 5)
    if not sources:
        return None, []
    snippets = " | ".join(f"{item['title']}: {item['snippet']}" for item in sources[:3])
    return f"Memory reminder: {snippets[:700]}", sources


async def answer_with_deepseek(query: str, sources: list[dict]) -> str:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY is not configured.")
    
    # Premium timestamp formatting for context sources
    context_lines = []
    for idx, item in enumerate(sources):
        created_at = item.get("created_at", "unknown")
        # Prettify the timestamp format for clear LLM readability
        if isinstance(created_at, str) and "T" in created_at:
            created_at = created_at.replace("T", " ").split(".")[0]
        context_lines.append(
            f"[{idx + 1}] (Created at: {created_at}) Type: {item['type']} - Title: {item['title']}\nContent: {item['snippet']}"
        )
    context = "\n\n".join(context_lines) or "No relevant memory was found."
    
    # Inject current local system time into DeepSeek system prompt
    current_time_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S (%Z)")
    system_prompt = (
        f"You are a helpful and precise personal memory assistant. Today's current date/time is {current_time_str}.\n"
        "Answer the user's question using ONLY the supplied personal memory context. "
        "Pay close attention to the 'Created at' timestamps of the memories relative to today's date "
        "to resolve temporal references like 'yesterday' (昨天), 'today' (今天), 'last week' (上周), etc. "
        "If a specific memory context is outside the requested time range of the user's query, DO NOT include it in your answer. "
        "If the memory context does not contain records from the requested timeframe, explicitly state that you could not find any records for that period. "
        "Keep your answer natural, concise, and in the same language as the user's query."
    )
    
    async with httpx.AsyncClient(timeout=30) as deepseek_client:
        response = await deepseek_client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Question: {query}\n\nMemory context:\n{context}"},
                ],
                "temperature": 0.2,
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"DeepSeek API error: {response.text[:500]}")
    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


init_voice_db()


CHINESE_NUMBERS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_chinese_number(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[value]
    if "十" in value:
        left, _, right = value.partition("十")
        tens = CHINESE_NUMBERS.get(left, 1) if left else 1
        ones = CHINESE_NUMBERS.get(right, 0) if right else 0
        return tens * 10 + ones
    if all(char in CHINESE_NUMBERS for char in value):
        number = 0
        for char in value:
            number = number * 10 + CHINESE_NUMBERS[char]
        return number
    return None


def normalize_explicit_anchor_time(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None

    numeric_match = re.search(r"\b([01]?\d|2[0-3])[:：]([0-5]\d)\b", text)
    if numeric_match:
        return f"{int(numeric_match.group(1)):02d}:{int(numeric_match.group(2)):02d}"

    am_pm_match = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text, re.IGNORECASE)
    if am_pm_match:
        hour = int(am_pm_match.group(1))
        marker = am_pm_match.group(2).lower()
        if marker == "pm" and hour != 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"

    chinese_hour = r"([零〇一二两三四五六七八九十]{1,3}|\d{1,2})"
    chinese_minute = r"([零〇一二两三四五六七八九十]{1,3}|\d{1,2})"
    time_match = re.search(
        rf"(?P<period>凌晨|早上|上午|中午|下午|傍晚|晚上|今晚|夜里|明早|明天早上|明天下午|明天晚上)?\s*"
        rf"(?P<hour>{chinese_hour})\s*(点|點|时|時)"
        rf"(?:(?P<half>半)|(?P<minute>{chinese_minute})\s*(分|分钟|刻)?)?",
        text,
    )
    if not time_match:
        return None

    hour = parse_chinese_number(time_match.group("hour"))
    if hour is None:
        return None

    if time_match.group("half"):
        minute = 30
    elif time_match.group("minute"):
        minute = parse_chinese_number(time_match.group("minute"))
        if minute is None:
            return None
    else:
        minute = 0

    period = time_match.group("period") or ""
    if period in {"下午", "傍晚", "晚上", "今晚", "夜里", "明天下午", "明天晚上"} and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12
    elif period in {"凌晨"} and hour == 12:
        hour = 0
    elif not period and 1 <= hour <= 6:
        hour += 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


SYSTEM_PROMPT = """
You are the advanced parsing engine for ChronoAI v2.0.
The user will provide a natural language text input describing a task. You must extract structured information and return a strict JSON object with the following fields:
{
  "name": "Task name, concise and under 10 Chinese/English characters. Strip away all time-related words (e.g. '下午', '晚上', '点半', '两小时', '2 hours', 'tomorrow') and keep only the core action, e.g. '写代码', '健身运动', '周报复盘', '看书学习'.",
  "category": "Must be exactly one of: 'work' (for professional or academic brain activities, e.g., coding, reports, meetings, analysis, deep learning, homework), 'health' (for physical health/exercise/rest, e.g., gym, running, yoga, meditation, sleep, medical), or 'personal' (for personal life/entertainment/chores, e.g., reading, shopping, chores, kids, friends, cooking, playing games).",
  "estMins": 30, // Estimated duration in minutes as a positive integer. Convert '1.5 hours', 'two hours', '半小时', etc. accurately. Default to 30 if not mentioned.
  "anchorTime": "15:00", // A specific starting time in 24-hour 'HH:MM' format if explicitly specified in the input (e.g., '下午三点', '15:00', '9:30', '10 o'clock'). Otherwise, return null.
  "confidence": "high" // Set to 'high' if the parsing is highly reliable, otherwise 'medium' or 'low'.
}

Example 1:
Input: "下午三点写量化策略报告两小时"
Output: {"name": "写策略报告", "category": "work", "estMins": 120, "anchorTime": "15:00", "confidence": "high"}

Example 2:
Input: "现在开始健身半小时"
Output: {"name": "健身运动", "category": "health", "estMins": 30, "anchorTime": null, "confidence": "high"}

Example 3:
Input: "读一小时小说"
Output: {"name": "看小说", "category": "personal", "estMins": 60, "anchorTime": null, "confidence": "high"}

Do NOT wrap the output in markdown formatting. Return ONLY a valid raw JSON object.
"""

async def call_gpt_parser(text: str) -> dict:
    if not openai_key:
        raise HTTPException(
            status_code=401, 
            detail="后端未配置 OPENAI_API_KEY。请在 backend/.env 中配置，或者在根目录放置 openai_key.txt。"
        )
    try:
        logger.info(f"[Parser] Sending prompt to GPT-4o-mini for text: '{text}'")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Validation & fallback checks
        result.setdefault("name", text[:10] if text else "新日程事项")
        result.setdefault("category", "work")
        result.setdefault("estMins", 30)
        result.setdefault("anchorTime", None)
        result.setdefault("confidence", "medium")
        
        # Coerce datatypes
        result["estMins"] = max(5, min(480, int(result["estMins"])))
        if result["category"] not in ["work", "health", "personal"]:
            result["category"] = "work"
        explicit_anchor_time = normalize_explicit_anchor_time(text)
        if explicit_anchor_time:
            result["anchorTime"] = explicit_anchor_time
            result["confidence"] = "high"
            
        logger.info(f"[Parser] Successfully parsed: {result}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[Parser] JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="AI 解析返回格式异常")
    except Exception as e:
        err_str = str(e)
        logger.error(f"[Parser] OpenAI API Error: {err_str}")
        if "insufficient_quota" in err_str or "429" in err_str:
            raise HTTPException(
                status_code=402, 
                detail="OpenAI API 余额不足。请前往 platform.openai.com 充值，或改用本地正则解析（前端已自动降级）。"
            )
        raise HTTPException(status_code=500, detail=f"AI 解析请求失败: {err_str}")

@app.post("/api/parse")
async def parse_text(req: ParseRequest):
    logger.info(f"Received parse request: {req.text}")
    if not req.text.strip():
        logger.warning("Empty text request received")
        raise HTTPException(status_code=400, detail="输入文本不能为空")
    return await call_gpt_parser(req.text)

@app.post("/api/text-parse")
async def parse_text_legacy(req: ParseRequest):
    # Keep legacy endpoint for compatibility, redirecting to /api/parse
    logger.info(f"Legacy text-parse endpoint called. Redirecting to /api/parse")
    return await call_gpt_parser(req.text)

@app.post("/api/voice-parse")
async def parse_voice(file: UploadFile = File(...)):
    filename = file.filename or "recording.webm"
    ext = os.path.splitext(filename)[1] or ".webm"
    logger.info(f"[Voice-Parse] Received upload file: '{filename}', extension: '{ext}'")
    
    if not openai_key:
        raise HTTPException(
            status_code=401, 
            detail="后端未配置 OPENAI_API_KEY。请在 backend/.env 中配置，或者在根目录放置 openai_key.txt。"
        )

    temp_file_path = None
    try:
        # 1. Save uploaded audio to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            temp_file_path = temp_file.name
        
        logger.info(f"[Voice-Parse] Temporary file written at: {temp_file_path}")

        # 2. Call OpenAI transcription API
        text = await transcribe_audio_file(temp_file_path)
        logger.info(f"[Voice-Parse] Transcript Result: '{text}'")
        
        if not text.strip():
            logger.warning("[Voice-Parse] Whisper returned empty transcription text")
            raise HTTPException(status_code=422, detail="未能从音频中识别出任何清晰文字")
        
        # 3. Call parser on transcribed text
        parsed_result = await call_gpt_parser(text)
        
        # Include transcription inside the result for frontend echo
        parsed_result["raw_text"] = text
        return parsed_result

    except Exception as e:
        err_str = str(e)
        logger.error(f"[Voice-Parse] ERROR: {err_str}")
        if "insufficient_quota" in err_str or "429" in err_str:
            raise HTTPException(
                status_code=402, 
                detail="OpenAI API 余额不足。请前往 platform.openai.com 充值，或改用本地打字正则解析。"
            )
        raise HTTPException(status_code=500, detail=f"语音听写解析失败: {err_str}")
    finally:
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"[Voice-Parse] Temporary file cleaned up: {temp_file_path}")
            except Exception as ex:
                logger.error(f"[Voice-Parse] Failed to delete temp file: {ex}")

@app.get("/health")
async def health_check():
    _, google_docs_auth_mode, google_docs_auth_email = resolve_google_docs_credentials()
    return {
        "status": "ok", 
        "service": "ChronoAI API Server", 
        "version": "2.0.0",
        "openai_configured": openai_key is not None and openai_key.startswith("sk-"),
        "voice_db_path": VOICE_DB_PATH,
        "gcs_configured": bool(GCS_BUCKET_NAME),
        "google_docs_enabled": GOOGLE_DOCS_ENABLED,
        "google_docs_configured": google_docs_auth_mode != "none",
        "google_docs_auth_mode": google_docs_auth_mode,
        "google_docs_auth_email": google_docs_auth_email,
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "deepseek_model": DEEPSEEK_MODEL if DEEPSEEK_API_KEY else None,
        "storage_mode": STORAGE_MODE,
        "index_mode": INDEX_MODE,
        "firestore_enabled": FIRESTORE_ENABLED,
        "firestore_project_id": FIRESTORE_PROJECT_ID or getattr(firestore_repo, "project_id", None),
        "firestore_collection": FIRESTORE_COLLECTION,
        "firestore_ready": bool(FIRESTORE_ENABLED and firestore_repo),
    }


@app.get("/api/voice/folders")
async def get_voice_folders():
    return load_voice_folders()


@app.get("/api/wiki/topics")
async def get_wiki_topics():
    return {"topics": WIKI_TOPICS}


@app.post("/api/wiki/entries")
async def create_wiki_entry(req: WikiEntryRequest):
    now = utc_now_iso()
    entry = {
        "id": f"wiki_{uuid.uuid4().hex}",
        "title": req.title.strip() or "Life Wiki Note",
        "body": req.body.strip(),
        "topic": req.topic if req.topic in WIKI_TOPICS else "personal_playbook",
        "tags": req.tags,
        "source": req.source or "manual",
        "confidence": req.confidence,
        "created_at": now,
        "updated_at": now,
    }
    if not entry["body"]:
        raise HTTPException(status_code=400, detail="Wiki body cannot be empty.")
    insert_wiki_entry(entry)
    return entry


@app.get("/api/wiki/entries")
async def get_wiki_entries(
    topic: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    return {"entries": list_wiki_entries(topic, q, limit)}


@app.get("/api/memory/search")
async def get_memory_search(
    q: str = Query(..., min_length=1),
    types: str = Query(default="wiki,journal"),
    limit: int = Query(default=8, ge=1, le=30),
):
    return {"results": await search_memory(q, types, limit)}


@app.post("/api/memory/ask")
async def ask_memory(req: MemoryAskRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    sources = await search_memory(query, req.types, max(1, min(req.limit, 30)))
    answer = await answer_with_deepseek(query, sources)
    return {"answer": answer, "sources": sources}


@app.get("/api/records")
async def get_records(
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=200),
):
    records, source = await list_records_any(category, limit, q)
    return {"records": records, "source": source, "limit": limit, "query": q or ""}


@app.post("/api/records")
async def post_record(req: RecordCreateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Record text cannot be empty.")
    category = normalize_record_category(req.category)
    now = datetime.now(timezone.utc)
    record = Record(
        id=build_record_id(),
        created_at=now,
        updated_at=now,
        source="voice" if req.source == "voice" else "text",
        raw_transcript=text,
        cleaned_text=text,
        category=category,
        category_label=CATEGORY_LABELS[category],
        confidence=1.0,
        needs_review=False,
        title=(req.title or text.splitlines()[0] or "Record")[:120],
        summary=(req.summary or text[:180]),
        metadata=RecordMetadata(tags=simple_tags_from_text(text)),
        storage_status={},
    )
    storage_status = await save_record_any(record)
    record.storage_status = storage_status
    return {"record": record_to_public_dict(record), "storage": storage_status}


@app.patch("/api/records/{record_id}")
async def patch_record(record_id: str, req: RecordUpdateRequest):
    return await update_record_any(record_id, req)


@app.delete("/api/records/{record_id}")
async def delete_record_endpoint(record_id: str):
    return await delete_record_any(record_id)


@app.patch("/api/records/{record_id}/category")
async def patch_record_category(record_id: str, req: RecordCategoryUpdateRequest):
    category = normalize_record_category(req.category)
    return await update_record_any(record_id, RecordUpdateRequest(category=category))


@app.get("/api/voice/entries")
async def get_voice_entries(
    folder_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    selected_folder = validate_folder_id(folder_id) if folder_id else None
    return {"entries": list_voice_entries(selected_folder, mode, limit)}


async def process_voice_submission(
    file: UploadFile | None,
    text: str | None,
    folder_id: str,
    mode: str,
    prompt_id: str | None,
) -> dict:
    requested_mode = (mode or "auto").strip().lower()
    if requested_mode not in {"auto", "journal", "schedule", "wiki", "ask"}:
        raise HTTPException(status_code=400, detail="mode must be one of: auto, journal, schedule, wiki, ask.")

    folder_id = validate_folder_id(folder_id or "LifeVoice")
    entry_id = f"voice_{uuid.uuid4().hex}"
    now = utc_now_iso()
    source = "voice" if file is not None else "text"
    transcript, audio_uri, source_filename, mime_type = await extract_submission_text(file, text, entry_id, folder_id)

    route = classify_voice_intent(transcript) if requested_mode == "auto" else {
        "intent": requested_mode,
        "confidence": 1.0,
        "reason": "manual mode",
    }
    resolved_mode = route["intent"]
    parsed_task = None
    wiki_entry = None
    answer = None
    sources = []

    if resolved_mode == "schedule":
        memory_note, sources = await build_memory_note(transcript)
        parsed_task = await call_gpt_parser(transcript)
        if memory_note:
            parsed_task["memory_note"] = memory_note
            parsed_task["memory_sources"] = sources
    elif resolved_mode == "wiki":
        wiki_entry = {
            "id": f"wiki_{uuid.uuid4().hex}",
            "created_at": now,
            "updated_at": now,
            **extract_wiki_entry_from_text(transcript),
        }
        insert_wiki_entry(wiki_entry)
    elif resolved_mode == "ask":
        sources = await search_memory(transcript, ["wiki", "journal"], 8)
        answer = await answer_with_deepseek(transcript, sources)

    record_draft = await create_record_draft(transcript, resolved_mode, source, route)
    record = build_record_from_draft(record_draft, transcript, source, now, resolved_mode)
    if resolved_mode != "ask":
        primary_result = append_record_to_google_doc(record, folder_id)
        record.storage_status = {
            "primary": primary_result,
            "index": {"backend": "sqlite", "status": "saved"},
        }
        index_result = insert_record(record, folder_id, resolved_mode, prompt_id)
        record.storage_status["index"] = index_result

        if FIRESTORE_ENABLED and firestore_repo:
            try:
                tags_str = ", ".join(record.metadata.tags) if record.metadata.tags else ""
                text_to_embed = f"Title: {record.title}\nSummary: {record.summary}\nContent: {record.cleaned_text}\nTags: {tags_str}"
                embedding = await get_text_embedding(text_to_embed)
                
                firestore_res = await firestore_repo.save_record(record, embedding=embedding)
                record.storage_status["firestore"] = firestore_res
            except Exception as fe:
                logger.error(f"[Firestore] Failed to save record: {fe}")
                record.storage_status["firestore"] = {"backend": "firestore", "status": f"failed: {fe}"}
    else:
        # Ask queries are transient. We do not persist them as permanent memory.
        primary_result = {
            "doc_id": None,
            "doc_url": None,
            "status": "skipped:ask_query_not_persisted"
        }
        record.storage_status = {
            "primary": primary_result,
            "index": {"backend": "sqlite", "status": "skipped:ask_query_not_persisted"},
            "firestore": {"backend": "firestore", "status": "skipped:ask_query_not_persisted"}
        }

    entry = {
        "id": entry_id,
        "mode": resolved_mode,
        "folder_id": folder_id,
        "prompt_id": prompt_id,
        "transcript": transcript,
        "audio_uri": audio_uri,
        "source_filename": source_filename,
        "mime_type": mime_type,
        "duration_ms": None,
        "parsed_task": parsed_task,
        "google_doc_id": primary_result.get("doc_id"),
        "google_doc_url": primary_result.get("doc_url"),
        "google_doc_status": primary_result.get("status"),
        "created_at": now,
        "updated_at": now,
    }

    insert_voice_entry(entry)

    return {
        "id": entry_id,
        "mode": resolved_mode,
        "route": route,
        "folder_id": folder_id,
        "transcript": transcript,
        "audio_uri": audio_uri,
        "created_at": now,
        "parsed_task": parsed_task,
        "wiki_entry": wiki_entry,
        "answer": answer,
        "sources": sources,
        "google_doc_id": entry.get("google_doc_id"),
        "google_doc_url": entry.get("google_doc_url"),
        "google_doc_status": entry.get("google_doc_status"),
        "ok": True,
        "record": {
            "id": record.id,
            "category": record.category,
            "category_label": record.category_label,
            "title": record.title,
            "summary": record.summary,
            "confidence": record.confidence,
            "needs_review": record.needs_review,
            "tags": record.metadata.tags,
            "created_at": record.created_at.isoformat(),
        },
        "storage": record.storage_status,
        "actions": [
            {"id": "change_category", "label": "Change category"},
            {"id": "edit", "label": "Edit"},
            {"id": "delete", "label": "Delete"},
        ],
    }


@app.post("/api/voice/submit")
async def submit_voice_entry(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    folder_id: str = Form(default="LifeVoice"),
    mode: str = Form(default="auto"),
    prompt_id: str | None = Form(default=None),
):
    return await process_voice_submission(file, text, folder_id, mode, prompt_id)


@app.post("/api/voice/transcribe")
async def transcribe_voice_entry(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    folder_id: str = Form(default="LifeVoice"),
    mode: str = Form(default="journal"),
    prompt_id: str | None = Form(default=None),
):
    return await process_voice_submission(file, text, folder_id, mode, prompt_id)


@app.post("/api/voice/draft")
async def voice_draft_endpoint(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    folder_id: str = Form(default="LifeVoice"),
    mode: str = Form(default="auto"),
):
    requested_mode = (mode or "auto").strip().lower()
    folder_id = validate_folder_id(folder_id or "LifeVoice")
    entry_id = f"voice_draft_{uuid.uuid4().hex}"
    
    transcript, audio_uri, source_filename, mime_type = await extract_submission_text(file, text, entry_id, folder_id)
    
    route = classify_voice_intent(transcript) if requested_mode == "auto" else {
        "intent": requested_mode,
        "confidence": 1.0,
        "reason": "manual mode",
    }
    resolved_mode = route["intent"]
    
    return {
        "transcript": transcript,
        "mode": resolved_mode,
        "ok": True
    }
