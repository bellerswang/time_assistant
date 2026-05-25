# ChronoAI - 智能自适应时间日程安排助理

欢迎来到 ChronoAI 项目。本项目是一款专为移动端（iOS / PWA）优化的时间日程安排助手。其核心价值在于“自适应效率纠偏”——通过采集用户的真实专注耗时，动态构建效率乘数模型，自适应伸缩日程长度并智能寻找空闲 Gap 进行插针，辅助用户掌控时间。

### v2.0.0 — 2026-05-24
**修改文件**: [index.html](file:///c:/Users/belle/OneDrive/Documents/PythonScripts/time_assistant/index.html), [backend/main.py](file:///c:/Users/belle/OneDrive/Documents/PythonScripts/time_assistant/backend/main.py)  
**更新内容**:
- **前端全量重构**: 使用高水准 Vanilla CSS 变量与设计系统重写 `index.html`。实现了 WeekStrip 7天滑动日程条、今日时间轴、Gap Finder 空闲探测、数据分析多维度指标（完成率、总时长、最准常规、最差时段）、常常规板管理（CRUD、效率乘数展示）等。
- **Bottom Sheets 手势与滑动收起**: 新增了智能语义解析 Sheet、新建/编辑常规模板 Sheet、删除确认 Sheet，完美兼容 iOS Safari 拖拽下拉 80px 自动滑出收缩手势。
- **自适应乘数算法**: 完成了基于最近 10 次真实耗时反馈的**线性滑动窗口加权效率乘数学习模型**，并在专注完成后闭环反哺更新，实现越用越精准的自校准时长预估。
- **后端服务接口规范对齐**: 增加了统一的 `/api/parse` 结构化日程大模型解析接口，并升级 `/api/voice-parse` 以对齐 v2.0 规格模型结构，增加对 `openai_key.txt` 根目录敏感密钥加载的支持，实现平滑离线正则引擎降级降本。
**当前状态**: ✅ 运行正常 / ⚠️ 已知问题: 无

---

## 🤖 智能体开发规范 (Agent Development Policy)

> [!IMPORTANT]
> **开发准则 (Project Policy)**：
> 1. 本文档 `README.md` 是 ChronoAI 项目的**唯一事实来源 (Single Source of Truth)**。
> 2. **每次对项目代码进行修改、更新、重构或架构调整后，智能体 (Agent) 必须首先更新本文档**，记录最新的更新日志、修改过的文件列表以及当前系统运行状态！
> 3. 开发过程中优先维护本地离线正则引擎作为平滑降级兜底，保障 100% 的高可用性。

---

## 🎯 项目目的与业务闭环

```
┌─────────────────────────────────────────────────────────┐
│                    ChronoAI 核心业务流                    │
└─────────────────────────────────────────────────────────┘
        │
        ├─► 1. 用户语音/文本输入（如："下午写代码两小时"）
        │
        ├─► 2. API 语音听写 (Whisper) 与大模型语义解析 (GPT-4o-mini)
        │
        ├─► 3. 历史效率自适应拉伸（根据分类偏差，将预估 60m 自动修正为 72m）
        │
        ├─► 4. 智能 Gap 扫描与插针（检索 08:00-22:00 空余，推荐最佳插针区间并附带理由）
        │
        ├─► 5. 用户确认并放入 Timeline日程轴 (LocalStorage 零延迟本地存储)
        │
        ├─► 6. 开启真实/加速计时专注 (断点防丢恢复)，完成后对比预估 vs 实际耗时
        │
        └─► 7. 更新效率偏差数据库，反馈迭代下一次插针模型 (越用越准)
```

---

## 💻 结构框架 (Architecture Framework)

项目采用**前后端分离**架构，前端天然兼容 Capacitor iOS 原生移动容器：

```
time_assistant/
│
├── venv/                       ◄── 【Python 虚拟环境】隔离运行环境，依赖已完全锁定 (httpx<0.28 冲突修复)
│
├── backend/                    ◄── 【FastAPI 服务端后端】
│   ├── .env                    ◄── OpenAI 敏感密钥 (OPENAI_API_KEY)
│   ├── requirements.txt        ◄── 后端依赖配置文件
│   └── main.py                 ◄── 后端主逻辑 (接收音频 Blob 进行 Whisper STT 听写，大模型 NLP 结构化提取)
│
├── index.html                  ◄── 【前端 H5 应用】MediaRecorder 音频录制，LocalStorage 本地存储，本地正则降级引擎
├── manifest.json               ◄── PWA iOS 沉浸式无边框桌面启动元数据
├── sw.js                       ◄── PWA 离线缓存服务工作线程
├── start_backend.bat           ◄── 【后端一键启动】自动校验激活 venv、增量 pip 并全网监听启动 uvicorn
└── start_frontend.bat          ◄── 【前端一键启动】自动获取本地局域网 IP，启动 Python 静态服务，自动拉起浏览器
```

---

## 📢 当前系统状况 (Current Status)

*   **后端服务**：
    *   已经在项目根目录下配置了独立的 `venv` 并修复了 `httpx` 版本冲突，支持以全网监听模式 (`--host 0.0.0.0`) 启动 FastAPI。
    *   提供 **`start_backend.bat`** 脚本一键傻瓜式启动。
*   **前端资源与部署**：
    *   因为浏览器安全限制，PWA 离线秒开 (Service Worker) 与 `manifest.json` **必须运行在 HTTP 协议环境**（不可直接用 `file://` 双击打开）。
    *   我为您创建了 **`start_frontend.bat`**。双击即可通过 Python 在端口 `8000` 极速起一个静态 HTTP 服务器，自动获取您 PC 的真实局域网 IP，并自动拉起默认浏览器。
    *   **动态 IP 穿透支持**：前端 `index.html` 的 `CONFIG.BACKEND_URL` 已升级为**动态主机识别**，无论是在本地电脑输入 `localhost` 还是在 iPhone 手机上输入局域网 IP (`192.168.x.x`)，前端均能**零修改代码、自适应直连**电脑上的后端 API 接口服务，实现了真正的一套代码全WiFi共享体验。
## v2.1.0 - Voice Recorder merge

ChronoAI is now the primary app for the former `voice_recorder` workflow.

- Added a dual-mode voice flow: `Schedule` mode turns speech into ChronoAI tasks, and `Journal` mode saves speech/text into Voice Inbox.
- Added backend voice APIs: `POST /api/voice/transcribe`, `GET /api/voice/entries`, and `GET /api/voice/folders`.
- Added SQLite voice metadata storage at `backend/data/chronoai.db` by default.
- Added optional Google Cloud Storage audio upload via `GCS_BUCKET_NAME`.
- Added Google Doc append for Journal mode using each folder's `gdrive_folder_id`.
- Switched backend transcription default to `gpt-4o-mini-transcribe`.
- Migrated folder config and reflection prompts into `folders.json` and `question_list.txt`.

Environment variables:

```bash
OPENAI_API_KEY=sk-...
GCS_BUCKET_NAME=your-bucket-name
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GOOGLE_DOCS_CREDENTIALS_PATH=backend/credential/key.json
GOOGLE_DOCS_CREDENTIALS_JSON={"type":"service_account",...}
GOOGLE_DOCS_ENABLED=true
VOICE_DB_PATH=backend/data/chronoai.db
VOICE_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

Cloud Run note: local SQLite is fine for local development and short trials, but Cloud Run's container filesystem is not reliable long-term storage. For production use, migrate voice metadata to Cloud SQL or Firestore while keeping audio files in GCS.

Google Docs sync note: Cloud Run can use either Application Default Credentials or `GOOGLE_DOCS_CREDENTIALS_JSON`. If local sync works but Cloud Run returns `permission_denied_share_doc`, share the target Google Doc with the service account shown by `/health` as `google_docs_auth_email`, or set `GOOGLE_DOCS_CREDENTIALS_JSON` to the same service account key used locally.

## v2.2.0 - Universal voice memory entry

- Added `Auto / Schedule / Journal / Wiki / Ask` voice modes.
- Added `POST /api/voice/submit` as the universal voice/text entrypoint.
- Added Life Wiki storage via `wiki_entries` and memory lookup via `/api/memory/search`.
- Added DeepSeek-backed `/api/memory/ask` for answers grounded in Journal + Wiki memory.
- Schedule parsing now attaches relevant memory reminders when matching journal/wiki context exists.

## Current workflows

### Universal voice entry

The voice sheet now defaults to `Auto`. A single voice/text submission can become:

- `Schedule`: creates a structured task preview and can attach memory reminders from Journal/Wiki.
- `Journal`: stores the transcript in Voice Inbox and appends it to the configured Google Doc.
- `Wiki`: stores reusable life knowledge as a structured Life Wiki card.
- `Ask`: searches Wiki + Journal memory and asks DeepSeek to answer from those sources.

Manual modes are still available: `Schedule`, `Journal`, `Wiki`, and `Ask`.

### Life Wiki

Life Wiki is for reusable knowledge, not time-ordered diary entries. Example:

```text
Colindale Library Bank Holiday does not open.
```

This should be saved as a Wiki card with a topic such as `places_local_life`, tags such as `library` and `bank holiday`, and a concise body. The database is the source of truth for search and AI context; Google Docs are only for human-readable journal backup.

### Memory search and Ask

Use `/api/memory/search?q=...&types=wiki,journal` to retrieve relevant memories. Use `/api/memory/ask` to ask DeepSeek for an answer grounded in those retrieved memories.

DeepSeek requires:

```bash
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

If `DEEPSEEK_API_KEY` is missing, Ask returns `503` but Journal, Wiki, and Schedule still work.

### Google Docs sync on Cloud Run

Local Google Docs sync can work while Cloud Run fails if the two environments use different Google identities. Check:

```text
https://voice-assistant-1090997558704.europe-west2.run.app/health
```

Important fields:

```json
{
  "google_docs_auth_mode": "service_account_json",
  "google_docs_auth_email": "xwang-upload@mercurial-weft-455321-v6.iam.gserviceaccount.com"
}
```

Recommended Cloud Run setup:

- Set environment variable name: `GOOGLE_DOCS_CREDENTIALS_JSON`
- Set value to the full service account JSON, including the outer `{}`.
- Keep `private_key` newline escapes as `\n`.
- Share the target Google Doc with `google_docs_auth_email` as Editor.

Common sync statuses:

- `synced`: transcript was appended to the Google Doc.
- `skipped:no_google_credentials`: Cloud Run has no usable Google credentials.
- `failed:permission_denied_share_doc`: share the target Doc with the backend service account.
- `failed:google_docs_api_disabled`: enable Google Docs API for the active project.
- `failed:doc_not_found_or_not_shared`: configured doc id is wrong or not shared with the service account.

### Cloud persistence note

Local SQLite is fine for development. Cloud Run container storage is not reliable long-term storage, so production memory should eventually move to Cloud SQL, Firestore, or another persistent backend. Until then, Cloud Run SQLite memory can disappear across container rebuilds or instance replacement.
