# ChronoAI v2.0 — Coding Agent 执行规格文档

**文档版本**: v2.0.0  
**目标文件**: `html_sample.html`（单文件全量重写）  
**执行模式**: 完整替换，不保留旧版本逻辑  
**优先级**: P0 全部实现，无可选项  

***

## 0. 执行前须知

1. 本文档是唯一事实来源，所有实现细节以本文档为准。
2. 所有数据存 localStorage，键名前缀统一用 `chrono_`。
3. 后端 API 调用保持现有 `CONFIG.BACKEND_URL` 动态主机识别逻辑不变。
4. 本地正则降级引擎必须完整保留，后端不可用时自动切换。
5. 全部逻辑写在单个 `html_sample.html` 文件内，不拆分外部 JS/CSS 文件。
6. 代码必须在 iOS Safari 17+ 和 Chrome 120+ 上正常运行。

***

## 1. 数据模型 (Data Schema)

### 1.1 localStorage 键名规范

| 键名 | 类型 | 说明 |
|------|------|------|
| `chrono_routines` | JSON Array | 固定常规任务模板库 |
| `chrono_tasks_{YYYY-MM-DD}` | JSON Array | 每天的任务实例列表 |
| `chrono_efficiency_log` | JSON Array | 效率偏差历史记录 |
| `chrono_settings` | JSON Object | 用户设置（主题、工作时段等） |

### 1.2 Routine 模板对象

```json
{
  "id": "rtn_1716547200000",
  "name": "晨间复盘",
  "category": "personal",
  "color": "#5ba8b5",
  "estMins": 20,
  "preferredTime": "08:00",
  "recurRule": "daily",
  "efficiencyMultiplier": 1.0,
  "efficiencyLogCount": 0,
  "createdAt": "2026-05-24T08:00:00.000Z"
}
```

字段说明：
- `recurRule`: `"daily"` | `"weekdays"` | `"weekly"` | `"none"`
- `preferredTime`: `"HH:MM"` 24小时制字符串，或 `null`
- `efficiencyMultiplier`: 浮点数，初始值 `1.0`，范围限制 `[0.5, 3.0]`
- `efficiencyLogCount`: 历史记录条数（用于置信度显示）

### 1.3 Task 实例对象

```json
{
  "id": "task_20260524_1716547200001",
  "routineId": "rtn_1716547200000",
  "name": "晨间复盘",
  "category": "work",
  "color": "#5ba8b5",
  "date": "2026-05-24",
  "scheduledStart": "08:00",
  "scheduledEnd": "08:20",
  "adjustedEstMins": 20,
  "status": "todo",
  "actualStart": null,
  "actualEnd": null,
  "actualMins": null,
  "isRoutineInstance": true,
  "isManuallyPlaced": false,
  "notes": ""
}
```

字段说明：
- `status`: `"todo"` | `"in_progress"` | `"done"` | `"skipped"`
- `routineId`: 来自模板则填模板ID，临时任务填 `null`
- `adjustedEstMins`: 已乘以 efficiencyMultiplier 后的修正时长
- `isManuallyPlaced`: 用户明确指定了时间则为 `true`

### 1.4 Efficiency Log 条目

```json
{
  "routineId": "rtn_1716547200000",
  "taskId": "task_20260524_001",
  "date": "2026-05-24",
  "estMins": 20,
  "actualMins": 25,
  "ratio": 1.25
}
```

***

## 2. 页面整体布局结构

```
┌─────────────────────────────────────────────┐
│  TopBar: Logo + 日期标题 + 设置按钮           │  固定顶部，高度 52px
├─────────────────────────────────────────────┤
│  WeekStrip: 横向 7 天日历条                   │  固定，高度 80px
├─────────────────────────────────────────────┤
│                                             │
│  MainContent: 当前 Tab 内容区域               │  滚动区域，flex-grow
│  (今日轴 / 分析 / 常规任务)                   │
│                                             │
├─────────────────────────────────────────────┤
│  VoiceFAB: 右下角浮动语音按钮                 │  fixed, bottom:90px
├─────────────────────────────────────────────┤
│  BottomNav: 3 Tab 导航栏                     │  固定底部，高度 64px + safe-area
└─────────────────────────────────────────────┘
```

### 2.1 TopBar 规格
- 左侧：SVG Logo（时钟图形）+ "ChronoAI" 文字
- 中间：当前选中日期，格式 `5月24日 周日`，点击可触发日期选择
- 右侧：设置图标按钮（预留，暂时 alert "即将推出"）

### 2.2 WeekStrip 规格
- 显示当前日期前后各 3 天，共 7 天
- 每个日期单元格显示：星期缩写（日/一/二...）、日期数字、当天任务数小圆点（最多 3 个）
- 选中状态：背景为主题色，文字白色，圆角 pill 形
- 今天额外标注 "今" 标签
- 支持左右滑动（touch event）以查看更多日期
- 点击日期切换主内容区到对应日期的时间轴

***

## 3. Tab 1 — 今日时间轴 (Timeline View)

### 3.1 顶部区域（在 MainContent 内，非固定）

**快捷操作栏**（横向滚动胶囊按钮组）:
- `[+ 一键载入常规]`: 将当天适用的 Routine 全部生成为 Task 实例，跳过已存在的，有冲突自动 push 到下一个空档
- `[今日概览]`: 显示当天统计（完成N/总N，专注Xmin）的简洁 banner

### 3.2 时间轴主体

**渲染逻辑**:
1. 读取 `chrono_tasks_{selectedDate}` 所有任务
2. 按 `scheduledStart` 时间字符串排序
3. 用 `08:00` 至 `22:00` 做时间范围
4. 每个时间块为一个 TaskCard

**TaskCard 设计规格**:

```
┌─────────────────────────────────────────────┐
│ 08:00  ●  ─────────────────────────────── │
│            晨间复盘                    [工作]│
│            预计 20min  →  实际 --min         │
│                         [跳过]  [▶ 开始]    │
└─────────────────────────────────────────────┘
```

- 左侧竖线时间轴：颜色根据任务 `color` 字段
- 状态圆点：todo=灰, in_progress=主题色+脉冲动画, done=绿色, skipped=红色
- 右侧 Badge: 显示 `category`（工作/个人/健康）
- 底部操作行:
  - **todo 状态**: `[跳过]` `[▶ 开始]`
  - **in_progress 状态**: 显示实时计时器（`HH:MM:SS`，每秒更新），`[■ 完成]`
  - **done 状态**: 显示 `✓ 完成 · 实际Xmin · 误差±Ymin`，无按钮
  - **skipped 状态**: 显示 `已跳过`，提供 `[撤销]` 按钮

**开始操作逻辑**:
```
点击 [▶ 开始]
  → task.status = "in_progress"
  → task.actualStart = ISO timestamp
  → 保存到 localStorage
  → 启动计时器（interval，每秒更新该卡片计时显示）
  → 同一天其他 in_progress 状态任务自动暂停（同时只允许一个进行中）
```

**完成操作逻辑**:
```
点击 [■ 完成]
  → task.status = "done"
  → task.actualEnd = ISO timestamp
  → task.actualMins = Math.round((actualEnd - actualStart) / 60000)
  → 保存到 localStorage
  → 如果 task.routineId 不为 null:
      → 读取对应 Routine
      → 写入 efficiency_log 一条记录
      → 重新计算该 Routine 的 efficiencyMultiplier（见第6节）
      → 保存 Routine
  → 显示完成 Toast: "✅ 完成！用时 Xmin，预估 Ymin"
```

**空白时间槽处理**:
- 如果相邻两个任务之间有 ≥30min 空档，插入一个视觉上的空白卡:
  ```
  │ 10:30  ○  ─── 空闲 45min ─── [+ 在此添加任务]
  ```
  点击 `[+ 在此添加任务]` 预填语义输入框并锁定时间为该空档开始时间

### 3.3 语义输入浮层（VoiceFAB 触发）

点击右下角麦克风 FAB 后，从底部弹出 Input Sheet:

```
┌─────────────────────────────────────────────┐
│  ━━━━                                       │  拖拽把手
│  告诉我你要做什么                             │  标题
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ 下午三点写量化策略报告，大概两小时...    │  │  textarea
│  └───────────────────────────────────────┘  │
│                                             │
│  [🎤 语音输入]          [✨ 解析并安排]      │
│                                             │
│  ── 解析结果预览 ──────────────────────────  │
│  任务: 写量化策略报告                        │
│  类别: 工作                                 │
│  预估: 120min → 修正后: 156min (×1.3)       │
│  时间: 15:00 锚定 → 15:00-17:36            │
│  理由: 您明确指定了 15:00，直接锚定。         │
│                                             │
│              [确认编入日程]                  │
└─────────────────────────────────────────────┘
```

**解析流程**:
1. 优先调用后端 `POST /api/parse` (CONFIG.BACKEND_URL)
2. 后端失败则降级到本地正则引擎（见第5节）
3. 解析结果显示预览卡
4. 点击 `[确认编入日程]` → 写入当天任务列表 → 关闭 Sheet → 滚动到新任务位置

***

## 4. Tab 2 — 数据分析 (Analytics View)

### 4.1 顶部时间范围选择器
胶囊 Tab: `[今天]` `[本周]` `[本月]`

### 4.2 统计卡片网格（2列）

| 卡片 | 内容 |
|------|------|
| 完成率 | X% (N/M 任务) |
| 专注时长 | X小时Y分钟 |
| 最准确任务 | [任务名] ±X% |
| 最低效时段 | XX:00 - XX:00 |

### 4.3 分类时间分布（横向进度条）

```
工作    ████████████░░░░  72%  3h 20min
个人    ███░░░░░░░░░░░░░  18%  50min
健康    ██░░░░░░░░░░░░░░  10%  28min
```

### 4.4 效率乘数趋势（Routine 维度）

列表展示每个 Routine 的当前 efficiencyMultiplier，配色：
- 绿色: `0.8 - 1.1`（接近准确）
- 黄色: `1.1 - 1.5`（偏慢，建议多排时间）
- 红色: `> 1.5`（严重低估）
- 蓝色: `< 0.8`（高估，完成比预期快）

### 4.5 原始数据导出
底部按钮 `[📤 导出 JSON]`，将三张表合并下载为 `chrono_export_{date}.json`

***

## 5. Tab 3 — 常规任务管理 (Routines Management)

### 5.1 列表视图

每个 Routine Card 显示：
```
┌─────────────────────────────────────────────┐
│ 🟦  晨间复盘                     [每天]      │
│     09:00 · 预计 20min · 工作               │
│     效率乘数: 1.2x  (基于 15 次记录)         │
│                          [编辑]  [删除]      │
└─────────────────────────────────────────────┘
```

颜色方块颜色 = Routine 的 `color` 字段

### 5.2 新增/编辑 Routine Sheet

底部弹出表单：

| 字段 | 组件 | 说明 |
|------|------|------|
| 任务名称 | text input | 必填 |
| 分类 | 3选1胶囊 (工作/个人/健康) | 必填 |
| 颜色 | 8色色板点选 | 必填，预设8个颜色 |
| 预计时长 | 数字输入 + "分钟" | 必填，正整数 |
| 偏好时间 | time input (HH:MM) | 可选，空则由 Gap Finder 决定 |
| 重复规则 | 4选1下拉 (每天/工作日/每周/不重复) | 必填 |

保存逻辑：
- 新增 → push 到 `chrono_routines` → 保存
- 编辑 → 找到对应 ID 更新 → 保存
- **不重置 efficiencyMultiplier**（编辑不清空学习数据）

### 5.3 删除确认

点击 `[删除]` → 底部弹出确认 Sheet:
```
确定删除"晨间复盘"？
已记录的 15 次效率数据也将一并删除。
历史任务实例不受影响。
[取消]  [确认删除]
```

***

## 6. 效率乘数算法实现

### 6.1 滑动窗口加权平均

```javascript
function recalculateMultiplier(routineId) {
  const allLogs = loadEfficiencyLogs();
  const logs = allLogs
    .filter(l => l.routineId === routineId)
    .slice(-10); // 取最近 10 条

  if (logs.length === 0) return 1.0;
  if (logs.length < 3) {
    // 数据不足时保守估计：简单平均
    const avg = logs.reduce((s, l) => s + l.ratio, 0) / logs.length;
    return Math.min(Math.max(avg, 0.5), 3.0);
  }

  // 线性加权（越近权重越高）
  const weights = logs.map((_, i) => i + 1); // [1,2,3,...10]
  const totalW = weights.reduce((a, b) => a + b, 0);
  const weightedRatio = logs.reduce((sum, log, i) =>
    sum + log.ratio * weights[i], 0) / totalW;

  return Math.min(Math.max(weightedRatio, 0.5), 3.0);
}
```

### 6.2 修正时长计算

```javascript
function getAdjustedMins(routine) {
  return Math.round(routine.estMins * routine.efficiencyMultiplier);
}
```

### 6.3 置信度标签

| 记录条数 | 置信度显示 |
|----------|-----------|
| 0-2 | `新任务` (灰色) |
| 3-9 | `学习中 (N次)` (蓝色) |
| 10-29 | `较准确 (N次)` (绿色) |
| 30+ | `高置信 (N次)` (深绿) |

***

## 7. Gap Finder 算法实现

### 7.1 核心逻辑

```javascript
function findBestGap(date, durationMins, preferAfter = null) {
  const tasks = loadTasks(date).filter(t => t.status !== 'skipped');
  const workStart = 8 * 60;  // 08:00 in minutes
  const workEnd = 22 * 60;   // 22:00 in minutes

  // 构建占用区间列表
  const occupied = tasks.map(t => ({
    start: timeToMins(t.scheduledStart),
    end: timeToMins(t.scheduledEnd)
  })).sort((a, b) => a.start - b.start);

  // 候选起始点：如果有 preferAfter，从该时间开始扫描
  const scanFrom = preferAfter
    ? Math.max(timeToMins(preferAfter), workStart)
    : workStart;

  // 扫描空档
  const gaps = [];
  let cursor = scanFrom;
  for (const busy of occupied) {
    if (busy.start > cursor) {
      gaps.push({ start: cursor, end: busy.start });
    }
    cursor = Math.max(cursor, busy.end);
  }
  if (cursor < workEnd) gaps.push({ start: cursor, end: workEnd });

  // 找第一个能放下 durationMins 的空档
  for (const gap of gaps) {
    if (gap.end - gap.start >= durationMins) {
      return {
        start: minsToTime(gap.start),
        end: minsToTime(gap.start + durationMins),
        reason: preferAfter
          ? `${minsToTime(gap.start)} 之后有连续 ${gap.end - gap.start}min 空档`
          : `全天最早可用空档`
      };
    }
  }
  return null; // 全天无空档
}
```

### 7.2 辅助函数

```javascript
function timeToMins(timeStr) {
  const [h, m] = timeStr.split(':').map(Number);
  return h * 60 + m;
}
function minsToTime(mins) {
  const h = Math.floor(mins / 60).toString().padStart(2, '0');
  const m = (mins % 60).toString().padStart(2, '0');
  return `${h}:${m}`;
}
```

***

## 8. 本地语义解析降级引擎

后端不可用时，使用本地正则引擎：

```javascript
function parseLocalFallback(text) {
  const result = {
    name: text,
    category: 'work',
    estMins: 30,
    anchorTime: null,
    confidence: 'local'
  };

  // === 时间锚点识别 ===
  const timePatterns = [
    /([01]?\d|2[0-3]):([0-5]\d)/,          // 14:00 格式
    /([01]?\d|2[0-3])点([0-5]\d分?)?/,      // 14点30 格式
    /下午(\d+)点/,   // 下午3点 → 15:00
    /上午(\d+)点/,   // 上午9点 → 09:00
    /早上(\d+)点/,   // 早上8点 → 08:00
    /晚上(\d+)点/,   // 晚上8点 → 20:00
  ];

  // 中文时间段映射
  const periodMap = {
    '早上': 8, '上午': 9, '中午': 12, '下午': 14, '傍晚': 17, '晚上': 19, '夜里': 21
  };

  for (const [period, hour] of Object.entries(periodMap)) {
    const match = text.match(new RegExp(period + '(\d+)点'));
    if (match) {
      result.anchorTime = minsToTime(hour * 60 + (parseInt(match[1]) - hour) * 60);
    }
  }

  const directTime = text.match(/([01]?\d|2[0-3]):([0-5]\d)/);
  if (directTime) {
    result.anchorTime = `${directTime[1].padStart(2,'0')}:${directTime[2]}`;
  }

  // === 时长识别 ===
  const durationPatterns = [
    [/(\d+)\s*小时\s*(\d+)\s*分/, m => parseInt(m[1])*60 + parseInt(m[2])],
    [/(\d+)\s*小时/, m => parseInt(m[1]) * 60],
    [/(\d+)\s*分钟/, m => parseInt(m[1])],
    [/半小时/, _ => 30],
    [/一个小时/, _ => 60],
    [/两个?小时/, _ => 120],
    [/三个?小时/, _ => 180],
    [/九十分钟/, _ => 90],
    [/四十五分钟/, _ => 45],
  ];

  for (const [pattern, extractor] of durationPatterns) {
    const match = text.match(pattern);
    if (match) { result.estMins = extractor(match); break; }
  }

  // === 任务名提取（去除时间和时长描述）===
  result.name = text
    .replace(/([01]?\d|2[0-3]):[0-5]\d/, '')
    .replace(/(上午|下午|早上|晚上|中午|傍晚)\d+点(\d+分)?/, '')
    .replace(/\d+小时(\d+分钟)?/, '')
    .replace(/\d+分钟/, '')
    .replace(/(半小时|一个?小时|两个?小时|三个?小时|九十分钟|四十五分钟)/, '')
    .replace(/，|,|\s+/g, ' ')
    .trim() || text;

  // === 分类识别 ===
  const catKeywords = {
    work: ['代码','报告','邮件','会议','分析','文档','数据','策略','Bloomberg','FOMC','量化','研究','周报','汇报','客户'],
    health: ['健身','跑步','瑜伽','锻炼','运动','冥想','睡觉','休息','散步'],
    personal: ['孩子','家庭','购物','阅读','看书','做饭','接送','学习','朋友']
  };

  for (const [cat, keywords] of Object.entries(catKeywords)) {
    if (keywords.some(kw => text.includes(kw))) {
      result.category = cat;
      break;
    }
  }

  return result;
}
```

***

## 9. 一键载入常规任务逻辑

```javascript
function loadRoutinesForDate(date) {
  const routines = loadRoutines();
  const existing = loadTasks(date);
  const dayOfWeek = new Date(date).getDay(); // 0=Sun, 6=Sat
  const isWeekday = dayOfWeek >= 1 && dayOfWeek <= 5;

  const applicable = routines.filter(r => {
    if (r.recurRule === 'daily') return true;
    if (r.recurRule === 'weekdays') return isWeekday;
    if (r.recurRule === 'weekly') {
      // 按创建日的星期匹配
      const createdDay = new Date(r.createdAt).getDay();
      return dayOfWeek === createdDay;
    }
    return false;
  });

  const newTasks = [];
  for (const routine of applicable) {
    // 跳过已存在的（同一 routineId 已有实例）
    if (existing.some(t => t.routineId === routine.id)) continue;

    const adjustedMins = getAdjustedMins(routine);

    // 确定时间
    let placement;
    if (routine.preferredTime) {
      // 有偏好时间：检查是否有冲突
      const prefStart = timeToMins(routine.preferredTime);
      const prefEnd = prefStart + adjustedMins;
      const allTasks = [...existing, ...newTasks];
      const conflict = allTasks.some(t => {
        const ts = timeToMins(t.scheduledStart);
        const te = timeToMins(t.scheduledEnd);
        return prefStart < te && prefEnd > ts;
      });

      if (!conflict) {
        placement = {
          start: routine.preferredTime,
          end: minsToTime(prefStart + adjustedMins)
        };
      } else {
        // 有冲突，从偏好时间之后找 Gap
        placement = findBestGap(date, adjustedMins, routine.preferredTime, [...existing, ...newTasks]);
      }
    } else {
      placement = findBestGap(date, adjustedMins, null, [...existing, ...newTasks]);
    }

    if (!placement) continue; // 全天无空档则跳过

    newTasks.push({
      id: `task_${date.replace(/-/g,'')}${Date.now()}${Math.random().toString(36).slice(2,6)}`,
      routineId: routine.id,
      name: routine.name,
      category: routine.category,
      color: routine.color,
      date: date,
      scheduledStart: placement.start,
      scheduledEnd: placement.end,
      adjustedEstMins: adjustedMins,
      status: 'todo',
      actualStart: null,
      actualEnd: null,
      actualMins: null,
      isRoutineInstance: true,
      isManuallyPlaced: false,
      notes: ''
    });
  }

  // 写入并返回新增数量
  const merged = [...existing, ...newTasks];
  saveTasks(date, merged);
  return newTasks.length;
}
```

***

## 10. 视觉设计规范

### 10.1 配色系统（深色为默认）

```css
:root {
  /* 深色主题 */
  --bg:          #0f0f0e;
  --surface:     #161614;
  --surface-2:   #1e1e1c;
  --surface-3:   #272725;
  --border:      #2e2e2b;
  --divider:     #252523;
  --text:        #e8e7e3;
  --text-muted:  #888884;
  --text-faint:  #4a4a47;
  --primary:     #5ba8b5;
  --primary-dim: rgba(91,168,181,0.15);
  --success:     #6daa45;
  --warning:     #e8af34;
  --error:       #d96b6b;
  --radius-sm:   6px;
  --radius-md:   10px;
  --radius-lg:   14px;
  --radius-xl:   20px;
  --radius-full: 9999px;
}
```

### 10.2 任务颜色预设（8色色板）

```javascript
const COLOR_PALETTE = [
  '#5ba8b5', // 蓝绿 (默认)
  '#6daa45', // 绿色
  '#e8af34', // 金黄
  '#d96b6b', // 红色
  '#a06bbf', // 紫色
  '#e07c3c', // 橙色
  '#5b8ab5', // 蓝色
  '#888884', // 灰色
];
```

### 10.3 字体

```css
font-family: 'SF Pro Display', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
```

### 10.4 关键动画

- 计时器数字：`font-variant-numeric: tabular-nums`，禁止 layout shift
- 状态圆点 in_progress：`animation: pulse 1.5s ease-in-out infinite`
- Sheet 弹出：`transform: translateY(100%) → translateY(0)`，`cubic-bezier(0.16, 1, 0.3, 1)`，duration 320ms
- Toast 出现：从上滑入，3秒后自动消失
- 任务完成：短暂绿色闪烁 + `✓` 图标替换

***

## 11. PWA / iOS 兼容性要求

- `<meta name="apple-mobile-web-app-capable" content="yes">`
- `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">`
- 所有固定元素需加 `padding-bottom: env(safe-area-inset-bottom)` 或 `padding-top: env(safe-area-inset-top)`
- 触摸目标最小 44×44px
- 禁止 `localStorage`/`sessionStorage` 访问失败导致崩溃，用 try/catch 包裹所有存取操作
- Bottom Sheet 滑动关闭：支持 `touchstart` / `touchmove` / `touchend` 手势识别，下滑超过 80px 自动关闭

***

## 12. localStorage 工具函数模板

```javascript
const DB = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch { return false; }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch {}
  }
};

const loadRoutines = () => DB.get('chrono_routines', []);
const saveRoutines = (data) => DB.set('chrono_routines', data);
const loadTasks = (date) => DB.get(`chrono_tasks_${date}`, []);
const saveTasks = (date, data) => DB.set(`chrono_tasks_${date}`, data);
const loadEfficiencyLogs = () => DB.get('chrono_efficiency_log', []);
const saveEfficiencyLogs = (data) => DB.set('chrono_efficiency_log', data);
```

***

## 13. 后端 API 接口规范（保持不变）

### POST /api/parse

Request:
```json
{ "text": "下午三点写量化策略报告两小时" }
```

Response:
```json
{
  "name": "写量化策略报告",
  "category": "work",
  "estMins": 120,
  "anchorTime": "15:00",
  "confidence": "high"
}
```

前端在收到 response 后：
1. 对 `estMins` 乘以对应分类的平均 `efficiencyMultiplier`（从同类 Routine 取平均，无则为 1.0）
2. 若 `anchorTime` 不为 null，直接用该时间；否则调用 `findBestGap`
3. 渲染预览卡等待用户确认

***

## 14. 更新日志规范

每次代码修改后，在 `README.md` 顶部追加：

```markdown
### v2.x.x — YYYY-MM-DD
**修改文件**: html_sample.html  
**更新内容**:
- [具体更改描述]
**当前状态**: ✅ 运行正常 / ⚠️ 已知问题: [描述]
```

***

## 15. 验收测试清单

Agent 完成代码后，必须自验以下场景：

- [ ] 首次打开，localStorage 为空，页面正常渲染（无报错）
- [ ] 新增 Routine，保存后刷新页面数据持久
- [ ] 点击"一键载入常规"，Routine 正确生成为当天 Task
- [ ] 有偏好时间的 Routine 与已有任务冲突时，自动 push 到下一空档
- [ ] 语义输入含时间锚点（如"16:00"），解析后 scheduledStart = "16:00"
- [ ] 语义输入不含时间，Gap Finder 正确找到空档
- [ ] 点击开始计时，计时器每秒更新，同一天其他任务自动暂停
- [ ] 点击完成，actualMins 正确计算，efficiencyMultiplier 更新
- [ ] WeekStrip 切换日期，MainContent 内容正确切换
- [ ] 在没有后端的情况下，本地降级引擎可以解析"明天下午写代码两小时"
- [ ] 导出 JSON 文件内容包含三张表完整数据
- [ ] iOS Safari 安全区域不遮挡内容
- [ ] 所有 Bottom Sheet 支持下滑手势关闭