下面是一个可以直接交给 Codex / Cursor / AI Agent 执行的 **UI 重构 coding plan**。目标是把现有 ChronoAI 从“日程管理 UI”改成“语音优先的个人记录智能体 UI”。

当前 README 显示，你的前端已有 `index.html`、MediaRecorder、PWA、LocalStorage、本地正则降级等基础；后端也已经有 `POST /api/voice/submit` 作为 universal voice entry，可以进入 Schedule / Journal / Wiki / Ask 流程。UI 重构应优先复用这些能力，而不是重写整个系统。

---

# 1. UI 重构目标

## 新产品心智

从：

```text
日程 / 时间轴 / Gap Finder / 效率分析
```

改成：

```text
打开 APP → 说一句 → 自动保存 → 可改分类 → 以后能问回来
```

## Level 1 UI 核心闭环

```text
Home 语音入口
  ↓
Recording Overlay
  ↓
Processing State
  ↓
Save Feedback Card
  ↓
Change Category Sheet
  ↓
Records List
  ↓
Ask from Records
```

---

# 2. 推荐最终页面结构

底部导航只保留 4 个 tab：

```text
Home | Records | Ask | Settings
```

不要在主导航里放：

```text
Timeline | Wiki | Journal | Schedule | Analytics | Gap Finder
```

这些旧功能先隐藏到 `Settings → Advanced Chrono Tools`。

---

# 3. 文件改造计划

你当前可以有两种做法。

## 方案 A：低风险，继续单文件 `index.html`

适合快速改。

```text
index.html
  - HTML templates
  - CSS variables
  - JS state
  - voice recording logic
  - API calls
  - UI rendering
```

优点是不用重构构建系统。
缺点是文件会继续变大。

---

## 方案 B：推荐，拆成前端模块

如果你准备认真维护，建议拆成：

```text
frontend/
├── index.html
├── styles.css
├── app.js
├── api.js
├── voice.js
├── state.js
├── components.js
└── utils.js
```

映射如下：

| 文件              | 职责                                                   |
| --------------- | ---------------------------------------------------- |
| `index.html`    | 页面骨架                                                 |
| `styles.css`    | 设计系统和组件样式                                            |
| `app.js`        | 初始化、路由、render                                        |
| `api.js`        | `/api/voice/submit`、`/api/records`、`/api/memory/ask` |
| `voice.js`      | MediaRecorder 录音逻辑                                   |
| `state.js`      | app state                                            |
| `components.js` | UI components                                        |
| `utils.js`      | 时间格式、分类 label、错误处理                                   |

如果你现在仍然想尽快跑起来，**先用方案 A**；等 UI 稳定后再拆成方案 B。

---

# 4. 信息架构改造

## 4.1 Home

职责：

```text
1. 大语音按钮
2. 最近 5 条记录
3. 最新保存反馈卡
4. 低置信度记录提示
```

Home 不再展示完整时间轴、Gap Finder、效率分析。

### Home wireframe

```text
┌─────────────────────────────┐
│ 今天有什么要记？              │
│                             │
│   工作想法 / 家庭安排 / 生活知识 │
│                             │
│             🎙              │
│          按住说话             │
│                             │
│ ─────────────────────────── │
│ 最近记录                     │
│                             │
│ 自我反思                     │
│ AI 产出焦虑与生活脱节          │
│ 昨天 22:30                   │
│                             │
│ 家庭安排                     │
│ 父母来伦敦后带娃状态变化       │
│ 5月20日                      │
└─────────────────────────────┘
```

---

## 4.2 Records

职责：

```text
1. 查看所有记录
2. 按分类筛选
3. 打开详情
4. 改分类
5. 编辑 / 删除，后续再做
```

筛选 chip：

```text
全部 | 工作想法 | 家庭安排 | 生活知识 | 自我反思 | 未分类
```

---

## 4.3 Ask

职责：

```text
1. 对已有记录提问
2. 显示回答
3. 显示来源
4. 点击来源打开原记录
```

Ask 不要做成普通 ChatGPT。它的 UI 必须强调：

```text
基于你的记录回答
```

---

## 4.4 Settings

职责：

```text
1. Google Doc sync status
2. OpenAI / DeepSeek API status
3. Storage mode: Google Doc now, Firestore reserved
4. Advanced Chrono Tools
5. Debug info
```

旧的 Timeline / Gap Finder / Analytics 先放这里：

```text
Settings
  └── Advanced Chrono Tools
      ├── Timeline
      ├── Gap Finder
      ├── Efficiency Analytics
      └── Routine Templates
```

---

# 5. 前端状态模型

建议加一个统一 `appState`。

```js
const appState = {
  activeTab: "home",

  recording: {
    status: "idle", // idle | recording | processing | error
    startedAt: null,
    durationSec: 0,
    error: null
  },

  latestFeedback: null,

  records: {
    items: [],
    activeFilter: "all",
    loading: false,
    error: null
  },

  ask: {
    input: "",
    loading: false,
    answer: null,
    sources: [],
    error: null
  },

  ui: {
    activeSheet: null, // changeCategory | recordDetail | advancedTools
    selectedRecordId: null
  }
};
```

核心原则：

> UI 只认识 `record`，不要在 UI 里直接写 Google Doc / Firestore 逻辑。

---

# 6. Record 数据结构

前端需要统一消费这个结构。

```js
const record = {
  id: "rec_20260525_183000_x7a9",
  created_at: "2026-05-25T18:30:00+01:00",

  category: "self_reflection",
  category_label: "自我反思",

  title: "AI 产出焦虑与生活脱节",
  summary: "反思 AI 工具带来的高产出感，以及这些产出没有真正融入生活的问题。",
  cleaned_text: "最近我陷入了……",

  tags: ["AI", "焦虑", "知识内化"],
  confidence: 0.86,
  needs_review: false,

  storage: {
    primary: "google_doc",
    status: "synced"
  }
};
```

分类映射：

```js
const CATEGORY_OPTIONS = [
  { value: "work_idea", label: "工作想法" },
  { value: "family_plan", label: "家庭安排" },
  { value: "life_knowledge", label: "生活知识" },
  { value: "self_reflection", label: "自我反思" },
  { value: "inbox", label: "未分类" }
];
```

---

# 7. 组件拆分计划

## 必须组件

```text
AppShell
BottomNav
HomeView
VoiceOrb
RecordingOverlay
ProcessingOverlay
SaveFeedbackCard
ChangeCategorySheet
RecordsView
RecordFilterChips
RecordCard
RecordDetailSheet
AskView
AskAnswerCard
SourceCard
SettingsView
```

---

## 7.1 `VoiceOrb`

职责：

```text
1. 按住开始录音
2. 松手结束录音
3. 上滑取消，后续做
4. 展示 recording 状态
```

伪代码：

```js
function VoiceOrb() {
  return `
    <button
      class="voice-orb"
      id="voiceOrb"
      aria-label="按住说话"
    >
      <span class="voice-icon">🎙</span>
      <span class="voice-label">按住说话</span>
    </button>
  `;
}
```

事件：

```js
voiceOrb.addEventListener("pointerdown", startRecording);
voiceOrb.addEventListener("pointerup", stopAndSubmitRecording);
voiceOrb.addEventListener("pointercancel", cancelRecording);
```

---

## 7.2 `RecordingOverlay`

```text
状态：正在听你说
显示：录音时长、波形/脉冲、松手保存
```

UI：

```text
┌─────────────────────────────┐
│ 正在听你说...                │
│                             │
│        ● ● ●                │
│        00:18                │
│                             │
│ 松手保存                     │
└─────────────────────────────┘
```

---

## 7.3 `ProcessingOverlay`

```text
状态：正在整理
显示：转文字、理解、保存
```

建议文案：

```text
正在整理你的记录...
```

不要显示太多技术细节。

---

## 7.4 `SaveFeedbackCard`

这是最关键的组件。

保存成功后展示：

```text
已保存为：自我反思

AI 产出焦虑与生活脱节

反思 AI 工具带来的高产出感，以及这些产出没有真正融入生活的问题。

[改分类] [打开] [删除]
```

状态规则：

| 情况                         | 文案                         |
| -------------------------- | -------------------------- |
| `confidence >= 0.8`        | `已保存为：xxx`                 |
| `0.55 <= confidence < 0.8` | `我理解为：xxx，已保存`             |
| `< 0.55`                   | `我不太确定，已放入未分类`             |
| Google Doc sync failed     | `已在本地记录，但 Google Doc 同步失败` |

---

## 7.5 `ChangeCategorySheet`

点击 `[改分类]` 弹出：

```text
改成哪一类？

工作想法
家庭安排
生活知识
自我反思
未分类
```

调用：

```http
PATCH /api/records/{record_id}/category
```

请求：

```json
{
  "category": "work_idea"
}
```

更新成功后：

```text
已改为：工作想法
```

---

## 7.6 `RecordsView`

结构：

```text
Records
[全部] [工作] [家庭] [知识] [反思] [未分类]

RecordCard
RecordCard
RecordCard
```

首次进入 Records 时调用：

```http
GET /api/records?limit=50
```

切换 filter 时：

```http
GET /api/records?category=work_idea&limit=50
```

---

## 7.7 `AskView`

结构：

```text
Ask my records

你可以问：
- 我最近关于 AI 焦虑说了什么？
- 我之前说过图书馆开放时间吗？
- 最近家庭状态有什么变化？

[输入问题...] [🎙]
```

调用：

```http
POST /api/memory/ask
```

响应后显示：

```text
你的记录显示：

...

来源：
1. 自我反思 · 2026-05-10
2. 工作想法 · 2026-05-24
```

---

# 8. API 对接计划

## 8.1 `POST /api/voice/submit`

前端提交 `FormData`：

```js
const formData = new FormData();
formData.append("audio", audioBlob, "voice.webm");
formData.append("mode", "auto");

const res = await fetch(`${CONFIG.BACKEND_URL}/api/voice/submit`, {
  method: "POST",
  body: formData
});
```

期待响应：

```json
{
  "ok": true,
  "transcript": "最近我陷入了 AI 焦虑...",
  "record": {
    "id": "rec_...",
    "category": "self_reflection",
    "category_label": "自我反思",
    "title": "AI 产出焦虑与生活脱节",
    "summary": "反思 AI 工具带来的高产出感...",
    "confidence": 0.86,
    "needs_review": false,
    "tags": ["AI", "焦虑"]
  },
  "storage": {
    "primary": {
      "backend": "google_doc",
      "status": "synced"
    }
  }
}
```

前端动作：

```text
1. appState.latestFeedback = response.record
2. 把 record 插入最近记录列表顶部
3. 显示 SaveFeedbackCard
4. recording.status = idle
```

---

## 8.2 `GET /api/records`

```js
async function fetchRecords(category = "all") {
  const query = category === "all" ? "" : `?category=${category}`;
  const res = await fetch(`${CONFIG.BACKEND_URL}/api/records${query}`);
  return await res.json();
}
```

---

## 8.3 `PATCH /api/records/{id}/category`

```js
async function updateRecordCategory(recordId, category) {
  const res = await fetch(`${CONFIG.BACKEND_URL}/api/records/${recordId}/category`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category })
  });

  return await res.json();
}
```

---

## 8.4 `POST /api/memory/ask`

```js
async function askMemory(question) {
  const res = await fetch(`${CONFIG.BACKEND_URL}/api/memory/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });

  return await res.json();
}
```

---

# 9. CSS 设计系统

建议走 **Calm Personal OS** 风格。

## 9.1 CSS variables

```css
:root {
  --bg: #f7f4ee;
  --surface: #ffffff;
  --surface-soft: #fbfaf7;
  --text: #1f2933;
  --text-muted: #6b7280;
  --border: rgba(31, 41, 51, 0.08);

  --accent: #3b6f63;
  --accent-soft: rgba(59, 111, 99, 0.12);
  --danger: #b94a48;

  --radius-sm: 10px;
  --radius-md: 16px;
  --radius-lg: 24px;
  --radius-full: 999px;

  --shadow-card: 0 12px 28px rgba(31, 41, 51, 0.08);
  --shadow-sheet: 0 -16px 40px rgba(31, 41, 51, 0.18);

  --safe-bottom: env(safe-area-inset-bottom);
}
```

## 9.2 Dark mode 预留

```css
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111827;
    --surface: #1f2937;
    --surface-soft: #18212f;
    --text: #f9fafb;
    --text-muted: #9ca3af;
    --border: rgba(255, 255, 255, 0.08);
    --accent: #7dd3c7;
    --accent-soft: rgba(125, 211, 199, 0.14);
  }
}
```

---

# 10. 关键样式组件

## 10.1 Voice Orb

```css
.voice-orb {
  width: 168px;
  height: 168px;
  border-radius: var(--radius-full);
  border: none;
  background: radial-gradient(circle at 35% 25%, #ffffff, var(--accent-soft));
  box-shadow: var(--shadow-card);
  color: var(--accent);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  touch-action: none;
}

.voice-orb.is-recording {
  transform: scale(1.04);
  box-shadow: 0 0 0 14px var(--accent-soft), var(--shadow-card);
}
```

---

## 10.2 Feedback Card

```css
.feedback-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}

.feedback-label {
  font-size: 13px;
  color: var(--accent);
  font-weight: 700;
}

.feedback-title {
  margin-top: 8px;
  font-size: 18px;
  line-height: 1.25;
  font-weight: 750;
}

.feedback-summary {
  margin-top: 10px;
  color: var(--text-muted);
  line-height: 1.5;
}
```

---

## 10.3 Bottom Sheet

你现在已有 Bottom Sheets 手势与滑动收起能力，可以复用。README 里也提到 v2.0 已实现多个 bottom sheet 和 iOS Safari 下拉收起手势。

```css
.bottom-sheet {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--surface);
  border-radius: 28px 28px 0 0;
  box-shadow: var(--shadow-sheet);
  padding: 16px 16px calc(16px + var(--safe-bottom));
  transform: translateY(100%);
  transition: transform 220ms ease;
  z-index: 50;
}

.bottom-sheet.is-open {
  transform: translateY(0);
}
```

---

# 11. 具体开发阶段

## Phase 0：更新 README

你的项目规范里要求每次改代码前先更新 README。README 目前也明确写了它是项目唯一事实来源，且重构后需要记录修改文件和当前状态。

新增：

```markdown
## v2.3.1 - Voice-first UI Refactor

- Refactored UI from schedule-first to voice-first capture.
- Added Home voice capture screen.
- Added SaveFeedbackCard after voice submission.
- Added Records tab with category filters.
- Added ChangeCategorySheet.
- Added Ask tab for memory-grounded questions.
- Moved Timeline, Gap Finder, Analytics, and Routine tools to Advanced Chrono Tools.
- Current storage remains Google Doc append, with Firestore reserved for future migration.
```

---

## Phase 1：建立 App Shell 和底部导航

### Tasks

```text
1. 移除首页强展示 WeekStrip / Timeline / Gap Finder
2. 新建 AppShell
3. 新建 BottomNav
4. 增加 activeTab 状态
5. 实现 Home / Records / Ask / Settings 四个 view 切换
```

### 验收标准

```text
底部导航可切换四个页面
旧功能没有删除，只是从首页移走
移动端底部 safe-area 正常
```

---

## Phase 2：重做 Home 页面

### Tasks

```text
1. 添加首页标题：“今天有什么要记？”
2. 添加 VoiceOrb
3. 添加最近记录区域
4. 添加 latestFeedback 区域
5. Home 初始加载 GET /api/records?limit=5
```

### 验收标准

```text
打开 APP 第一眼看到语音按钮
最近记录最多显示 5 条
没有时间轴压迫感
```

---

## Phase 3：录音状态 UI

### Tasks

```text
1. 把现有 MediaRecorder 逻辑接到 VoiceOrb
2. pointerdown 开始录音
3. pointerup 停止并提交
4. recording.status = recording 时显示 RecordingOverlay
5. 提交时显示 ProcessingOverlay
6. 出错时显示 error toast/card
```

### 验收标准

```text
按住说话可以录音
松手后自动提交
处理时有明确 loading
失败时不丢 UI 状态
```

---

## Phase 4：接入 `/api/voice/submit`

### Tasks

```text
1. 封装 submitVoice(audioBlob)
2. FormData 上传音频
3. mode 固定传 auto
4. 解析 response.record
5. 显示 SaveFeedbackCard
6. 插入 records.items 顶部
```

### 验收标准

```text
录完一句话后自动保存
保存结果以卡片展示
显示分类、标题、摘要、tags
Google Doc sync 状态可以在小字里展示
```

---

## Phase 5：SaveFeedbackCard

### Tasks

```text
1. 根据 confidence 显示不同文案
2. 添加 [改分类]
3. 添加 [打开记录]
4. 添加 [删除] 但可以先 disabled
5. Google Doc sync failed 时显示 warning
```

### UI 规则

```js
function getFeedbackCopy(record) {
  if (record.confidence >= 0.8) {
    return `已保存为：${record.category_label}`;
  }

  if (record.confidence >= 0.55) {
    return `我理解为：${record.category_label}，已保存`;
  }

  return "我不太确定，已放入未分类";
}
```

### 验收标准

```text
高置信度：已保存为 xxx
中置信度：我理解为 xxx
低置信度：未分类
```

---

## Phase 6：ChangeCategorySheet

### Tasks

```text
1. 点击 [改分类] 打开 bottom sheet
2. 显示五个分类
3. 点击分类调用 PATCH /api/records/{id}/category
4. 成功后更新当前 card 和 records list
5. 显示 toast：“已改为：工作想法”
```

### 分类

```text
工作想法
家庭安排
生活知识
自我反思
未分类
```

### 验收标准

```text
保存后可以一键改分类
Records 页面同步显示新分类
不需要刷新页面
```

---

## Phase 7：Records 页面

### Tasks

```text
1. 新建 RecordsView
2. 加 filter chips
3. 加 RecordCard
4. 点击 RecordCard 打开 RecordDetailSheet
5. 支持下拉刷新，后续可做
```

### RecordCard 字段

```text
category_label
title
created_at
summary
tags
needs_review marker
```

### 验收标准

```text
可以看全部记录
可以按分类筛选
可以打开详情
可以在详情里改分类
```

---

## Phase 8：Ask 页面

### Tasks

```text
1. 新建 AskView
2. 输入框 + 语音按钮，语音按钮后续可复用 VoiceOrb mini version
3. 调用 POST /api/memory/ask
4. 显示回答
5. 显示 sources
6. 点击 source 打开对应 RecordDetailSheet
```

### 验收标准

```text
可以问“我最近关于 AI 焦虑说了什么？”
回答有来源
来源能打开原记录
DeepSeek 缺失时显示明确错误
```

---

## Phase 9：Settings + Advanced Chrono Tools

### Tasks

```text
1. Settings 显示当前 storage mode: Google Doc
2. 显示 Firestore reserved / disabled
3. 显示 Google Docs sync status
4. 把旧的 Timeline / Gap Finder / Analytics 放进 Advanced
5. 保留旧功能入口，但不在首页显示
```

### 文案建议

```text
Storage
Current: Google Doc append
Index: SQLite
Future: Firestore reserved
```

### 验收标准

```text
用户知道当前数据仍然写 Google Doc
旧功能没有消失
首页不再复杂
```

---

# 12. 不要做的 UI

这次重构不要做：

```text
1. 首页展示完整 WeekStrip
2. 首页展示 Gap Finder
3. 首页展示效率乘数
4. 首页展示太多统计
5. 录音前让用户选择 Schedule / Journal / Wiki / Ask
6. 每次保存都强制确认
7. 复杂知识库编辑器
```

这些都会破坏“随时随地快速记录”的主体验。

---

# 13. 最终验收标准

## 核心体验验收

```text
1. 打开 APP 后 1 秒内能看到语音入口
2. 一次录音可以自动保存
3. 保存后能看到分类、标题、摘要
4. 错分类可以两次点击内修正
5. Records 能看到历史记录
6. Ask 能基于历史记录回答并显示来源
7. Google Doc 仍然是当前录入落点
8. Firestore 不启用，但 UI 和代码不绑定 Google Doc
```

---

# 14. 推荐给 Codex 的任务顺序

可以直接这样拆任务：

```text
Task 1:
Update README with v2.3.1 Voice-first UI Refactor plan.

Task 2:
Refactor front-end app shell to use four tabs: Home, Records, Ask, Settings. Move existing Chrono timeline tools into Settings > Advanced Chrono Tools.

Task 3:
Build HomeView with a large central VoiceOrb, recent records list, and latest SaveFeedbackCard area.

Task 4:
Connect VoiceOrb to existing MediaRecorder logic. Show RecordingOverlay while recording and ProcessingOverlay while submitting.

Task 5:
Update /api/voice/submit client handling so the response renders SaveFeedbackCard with category, title, summary, tags, confidence, and storage status.

Task 6:
Add ChangeCategorySheet and connect it to PATCH /api/records/{record_id}/category.

Task 7:
Build RecordsView with filter chips and RecordCard list using GET /api/records.

Task 8:
Build AskView using POST /api/memory/ask and render answer with source cards.

Task 9:
Add Settings storage panel showing Google Doc as current active storage and Firestore as reserved future storage.

Task 10:
Polish CSS variables, mobile safe-area, bottom sheets, dark mode, and empty/error states.
```

---

# 15. 最终 UI 重构结果

重构后，你的 APP 会从：

```text
一个日程工具，附带语音记录功能
```

变成：

```text
一个语音优先的个人记录智能体，当前写入 Google Doc，未来可迁移 Firestore
```

这是这次 UI coding plan 的核心。
