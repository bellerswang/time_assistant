# ChronoAI v3.0 — Google Calendar 深度自适应日程执行规格文档

**文档版本**: v3.0.0  
**目标文件**: `index.html`（在 v2.0 基础上增量重构与深度升级）  
**核心目标**: 引入 Google OAuth 2.0 与 Google Calendar API，实现客户端直接双向同步日历、防冲突 Gap Finder 算法升级、以及安全持久化授权管理。  
**执行模式**: 全面覆盖 `plan.md`，并在前端 `index.html` 落地所有 Google Calendar 逻辑，维持无外置 JS/CSS 的单网页优雅架构，同时确保后端 API 正常工作。

***

## 0. 执行前须知

1. **核心原则**: 不引入复杂的服务器端数据库及 OAuth 授权代理，将 Google OAuth 2.0 与 Google Calendar 读写操作完全在**客户端浏览器（Frontend Only）**中实现，确保系统的极简化部署与用户隐私安全性。
2. **Client ID 配置**: 用户可通过系统 Settings 面板，自助输入其在 Google Cloud Console 申请的 **OAuth 2.0 Web Client ID**，系统将其保存在 `localStorage` 中。
3. **安全跨域**: GitHub Pages (HTTPS) 与本地 `http://localhost:8000` / `http://127.0.0.1:8000` 作为授权回调源（Authorized JavaScript Origins）可直接配合 Google 客户端授权服务（Google Identity Services）使用，无 CORS 限制。
4. **混合数据**: Google Calendar 日程在时间轴上作为一种特殊的“只读锁定卡片”存在，直接参与 Gap Finder 空闲时段计算，但不参与效率乘数计算，亦不可随意拖拽或点击“开始/完成”。
5. **本地降级**: 在无网络或 Google 授权过期时，系统应保持完全可用的状态，Google 日历部分优雅显示为“离线缓存/授权失效”，不阻塞本地核心功能运行。

***

## 1. 数据模型 (Data Schema)

### 1.1 localStorage 键名规范

在 v2.0 的基础上，新增以下 Google Calendar 相关缓存与配置键：

| 键名 | 类型 | 说明 |
|------|------|------|
| `chrono_gcal_token` | String | Google OAuth 2.0 客户端 `access_token` |
| `chrono_gcal_expires_at` | Number | `access_token` 的过期时间戳（单位：毫秒，Epoch Time） |
| `chrono_gcal_settings` | JSON Object | Google Calendar 同步偏好设置 |
| `chrono_gcal_events_{YYYY-MM-DD}` | JSON Array | 缓存的该日期 Google Calendar 日程实例，供离线及快速加载使用 |

### 1.2 Google Calendar 同步配置对象 (`chrono_gcal_settings`)

```json
{
  "clientId": "your-google-client-id.apps.googleusercontent.com",
  "calendarId": "primary",
  "enabled": true,
  "autoImport": true,
  "autoExport": false,
  "exportCalendarId": "primary",
  "lastSyncedAt": "2026-05-24T17:45:00.000Z"
}
```

字段说明：
- `clientId`: Google Cloud 控制台创建的 OAuth 2.0 Web 应用客户端 ID。
- `calendarId`: 同步源日历，默认值为 `"primary"`。
- `enabled`: 是否启用 Google Calendar 功能。
- `autoImport`: 切换日期或加载页面时，是否自动在后台同步最新的 Google 日历事件。
- `autoExport`: 本地创建或完成的任务，是否自动写入（导回）到 Google 日历。

### 1.3 Google Calendar 事件对象 (`GCal Event`)

导入至本地时间轴渲染的 GCal 事件直接重用（并扩展）Task 实例格式，确保渲染引擎兼容：

```json
{
  "id": "gcal_1716547200000_20260524evt123",
  "routineId": null,
  "name": "公司周度量化业务对齐会",
  "category": "work",
  "color": "#4285f4",
  "date": "2026-05-24",
  "scheduledStart": "09:30",
  "scheduledEnd": "10:30",
  "adjustedEstMins": 60,
  "status": "todo",
  "actualStart": null,
  "actualEnd": null,
  "actualMins": null,
  "isRoutineInstance": false,
  "isManuallyPlaced": true,
  "isGCalEvent": true,
  "gcalEventId": "evt123456789abcde",
  "notes": "主要内容：讨论下周 Bloomberg 终端数据接入与量化回测框架。"
}
```

核心差异属性：
- `isGCalEvent`: 标记为 `true`。渲染引擎识别此标记后，屏蔽常规 TaskCard 的“开始、跳过、完成”等动作栏，改为显示“🔒 Google 日历锁”与“🔗 在 Google 日历中打开”图标。
- `color`: 默认为 Google Calendar 经典蓝色 `#4285f4`，或支持读取 Google Event 颜色，与本地任务色板进行视觉区分。
- `status`: 固定为 `"todo"` 或根据当前时间是否已过去进行视觉淡化，无需手动更新。

***

## 2. 页面整体布局结构

```
┌─────────────────────────────────────────────┐
│  TopBar: Logo + 日期标题 + 设置按钮           │  固定顶部，高度 52px
├─────────────────────────────────────────────┤
│  WeekStrip: 横向 7 天日历条                   │  固定，高度 80px
├─────────────────────────────────────────────┤
│  GCalStatusBar: 日历同步快捷状态条 (New!)     │  高度 28px，可折叠/仅在同步时出现
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

### 2.1 顶部日历同步状态条 (GCalStatusBar)
- 仅在启用 Google Calendar 后渲染于 WeekStrip 下方。
- 左侧显示最新同步时间：“🔄 日历已同步: 17:45”，右侧提供点击手动触发强制同步图标。
- 当 Token 提示过期或未绑定时，呈现极简黄色状态指示：“⚠️ Google 授权已过期 [重新连接]”。

### 2.2 设置面板 (`sheet-settings`) 升级
增加折叠面板“🌐 Google Calendar 集成”，包含以下组件：
1. **Client ID 配置项**: 输入框，支持绑定 Google Cloud Client ID，带 `[保存]` 键。
2. **状态指示**: `🟢 已成功绑定` / `🟡 未授权/授权已过期` / `🔴 未配置 Client ID`。
3. **操作按键**:
   - `[🔗 授权并连接 Google 日历]`：触发 GIS 授权弹窗。
   - `[🔌 解除绑定]`：清除本地 token 及缓存。
4. **选项开关组**:
   - 切换开关 1: 自动导入日历事件为忙碌空档 (localStorage 默认持久)
   - 切换开关 2: 允许同步 ChronoAI 新增任务至 Google 日历

***

## 3. Tab 1 — 今日时间轴 (Timeline View)

### 3.1 混合时间轴排序与渲染逻辑
1. 载入当前日期 `chrono_tasks_{selectedDate}` 的所有本地任务。
2. 若 Google Calendar 已开启且有 `chrono_gcal_events_{selectedDate}` 缓存，读取该缓存并与本地任务**合并（Merge）**。
3. **统一排序**：将合并后的列表按 `scheduledStart` 进行 24 小时升序排列。
4. 渲染任务轴，识别 `isGCalEvent === true` 的卡片，应用专属 Google Calendar 样式。

### 3.2 GCal TaskCard 专属设计规格

```
┌─────────────────────────────────────────────┐
│ 09:30  ●  ─────────────────────────────── │
│        📅  公司周度量化业务对齐会         [日历]│
│            09:30 - 10:30  🔒 锁定占用        │
│                         [🔗 在 Google 日历打开]│
└─────────────────────────────────────────────┘
```

- **左侧时间轴**: 连线使用特殊的 Google 蓝色渐变 (`linear-gradient(180deg, #4285f4 0%, var(--primary) 100%)`)。
- **背景风格**: 具有极高阶质感的半透明微毛玻璃效果，边框为半透明淡蓝色 (`rgba(66, 133, 244, 0.2)`)。
- **右上角 Badge**: 显示带有小图标的 “📅 谷歌日历” 或 “🔒 日历锁定”。
- **禁止本地操作**: 卡片底部无“开始”、“完成”按钮。避免本地数据对第三方数据直接篡改。
- **链接外跳**: 提供极简的 `[🔗 在 Google 日历打开]` 外部链接按钮（点击跳转至 Google Web Calendar 的该日程编辑详情页，链接格式：`https://calendar.google.com/calendar/r/eventedit/${gcalEventId}` 或通用日历入口）。

***

## 4. Tab 2 — 数据分析 (Analytics View)

在计算专注时长、效率分类时：
- **数据剔除**: Google Calendar 导入的只读事件**不纳入**本地自适应效率乘数的机器学习计算（剔除出 `chrono_efficiency_log`）。
- **时间占用计算**: 在计算当天“空闲与忙碌时间比例”时，Google Calendar 的事件将被纳入“忙碌时间总量”，使用户能看到真实的时间分配比例。
- **分类呈现**: Google Calendar 的事件可根据其名称或默认类别被分类展示（如名称含“会”、“周会”、“Report”等自动分类为 `work`；含“Doctor”、“跑步”分类为 `health`）。

***

## 5. Tab 3 — 常规任务管理 (Routines Management)

- **冲突拦截**: 当用户新增 Routine 模板，或试图在当天手动排入某一任务模板时，系统在“一键载入”或手动选择时，会自动分析是否与当天已存在的 Google 日历事件发生重叠。
- **自动顺延**: 如果常规任务 PreferredTime 刚好撞上 Google 日历的“紧急晨会”，系统将自动启用 Gap Finder，将常规任务顺延至该晨会结束后的第一个黄金空档。

***

## 6. Google OAuth 2.0 & GIS 技术实现

### 6.1 Google Identity Services 客户端载入
在 `index.html` 的 `<head>` 中动态或静态引入 Google GIS 官方 JavaScript SDK：
```html
<script src="https://accounts.google.com/gsi/client" async defer></script>
```

### 6.2 客户端 Token 认证流程
系统基于 GIS 的 `TokenClient` 实现隐式授权，获取 Access Token 并操作客户端 REST API：

```javascript
let tokenClient = null;

// 初始化 Google Identity Client
function initGCalClient() {
    const settings = DB.get('chrono_gcal_settings', {});
    if (!settings.clientId) return;

    try {
        tokenClient = google.accounts.oauth2.initTokenClient({
            client_id: settings.clientId,
            scope: 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/calendar.events',
            callback: (tokenResponse) => {
                if (tokenResponse.error) {
                    showToast(`⚠️ 授权失败: ${tokenResponse.error}`, 'error');
                    return;
                }
                
                // 保存 Access Token 及其过期时间 (秒转毫秒)
                const expiresAt = Date.now() + (parseInt(tokenResponse.expires_in) * 1000);
                DB.set('chrono_gcal_token', tokenResponse.access_token);
                DB.set('chrono_gcal_expires_at', expiresAt);
                
                // 启用设置
                settings.enabled = true;
                DB.set('chrono_gcal_settings', settings);
                
                showToast('🟢 Google Calendar 授权成功，正在拉取数据...', 'success');
                syncGCalEvents(getTodayString());
                
                // 刷新 UI
                updateSettingsPanelUI();
            },
        });
    } catch (e) {
        console.error('Failed to initialize GIS TokenClient:', e);
    }
}

// 触发用户授权弹窗
function connectGoogleAccount() {
    const settings = DB.get('chrono_gcal_settings', {});
    if (!settings.clientId) {
        showToast('⚠️ 请先保存有效的 Google Client ID', 'error');
        return;
    }
    if (!tokenClient) {
        initGCalClient();
    }
    if (tokenClient) {
        tokenClient.requestAccessToken({ prompt: 'consent' });
    } else {
        showToast('⚠️ Google SDK 载入失败，请检查网络或稍后重试', 'error');
    }
}
```

***

## 7. Google Calendar API REST 交互逻辑

由于是 Frontend Only 结构，直接使用 `fetch` 访问 Google 日历 API v3：

### 7.1 获取日历事件列表 (`GET https://www.googleapis.com/...`)
调用此接口拉取用户在当前选中日期（以及前后共 3 天的范围，以供快速滑页）的所有日程事件，并解析保存到 `chrono_gcal_events_{date}`：

```javascript
async function syncGCalEvents(dateStr) {
    const settings = DB.get('chrono_gcal_settings', {});
    if (!settings.enabled || !settings.clientId) return;
    
    // 检查 Token 是否存在且未过期
    const token = DB.get('chrono_gcal_token');
    const expiresAt = DB.get('chrono_gcal_expires_at', 0);
    
    if (!token || Date.now() >= expiresAt - 60000) { // 留出 1 分钟宽限期
        showToast('⚠️ 谷歌授权已失效，请在设置中重新连接', 'warning');
        updateSyncStatusUI(false);
        return;
    }
    
    const calId = encodeURIComponent(settings.calendarId || 'primary');
    
    // 确定查询的起止时间范围 (本地时间转换为 ISO 格式)
    const targetDate = new Date(dateStr);
    const startOfDay = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate(), 0, 0, 0);
    const endOfDay = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate(), 23, 59, 59);
    
    const timeMin = startOfDay.toISOString();
    const timeMax = endOfDay.toISOString();
    
    const url = `https://www.googleapis.com/calendar/v3/calendars/${calId}/events?timeMin=${timeMin}&timeMax=${timeMax}&singleEvents=true&orderBy=startTime`;
    
    try {
        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                // Token 过期失效
                DB.remove('chrono_gcal_token');
                showToast('🔑 授权失效，请重新连接 Google 账号', 'error');
                updateSyncStatusUI(false);
                return;
            }
            throw new Error(`GCal Sync Error: ${response.status}`);
        }
        
        const data = await response.json();
        const rawEvents = data.items || [];
        
        // 映射为本地 GCal Event 格式
        const gcalTasks = rawEvents.map(evt => {
            const startStr = evt.start.dateTime || evt.start.date; // 兼容全天事件
            const endStr = evt.end.dateTime || evt.end.date;
            
            const startDt = new Date(startStr);
            const endDt = new Date(endStr);
            
            const startHM = startDt.toTimeString().slice(0, 5); // "HH:MM"
            const endHM = endDt.toTimeString().slice(0, 5);
            
            const estMins = Math.round((endDt - startDt) / 60000);
            
            // 自动推算 category
            let category = 'personal';
            const textToAnalyze = (evt.summary + ' ' + (evt.description || '')).toLowerCase();
            const workKeywords = ['code', 'meeting', 'standup', '周报', '工作', '汇报', '会议', '对齐', '开发'];
            const healthKeywords = ['gym', 'yoga', 'hospital', '健身', '医院', '睡觉', '运动'];
            if (workKeywords.some(kw => textToAnalyze.includes(kw))) category = 'work';
            else if (healthKeywords.some(kw => textToAnalyze.includes(kw))) category = 'health';
            
            return {
                id: `gcal_${startDt.getTime()}_${evt.id}`,
                routineId: null,
                name: evt.summary || '无标题日历事件',
                category: category,
                color: '#4285f4', // Google Blue
                date: dateStr,
                scheduledStart: startHM,
                scheduledEnd: endHM,
                adjustedEstMins: estMins,
                status: 'todo',
                actualStart: null,
                actualEnd: null,
                actualMins: null,
                isRoutineInstance: false,
                isManuallyPlaced: true,
                isGCalEvent: true,
                gcalEventId: evt.id,
                notes: evt.description || ''
            };
        });
        
        // 存入对应的本地日期缓存中
        DB.set(`chrono_gcal_events_${dateStr}`, gcalTasks);
        
        // 更新同步状态与 UI
        settings.lastSyncedAt = new Date().toISOString();
        DB.set('chrono_gcal_settings', settings);
        
        updateSyncStatusUI(true);
        if (currentTab === 'timeline') renderTimeline();
        
    } catch (err) {
        console.error('Failed to sync google calendar events:', err);
        showToast('⚠️ Google 日历同步失败，请检查网络', 'error');
    }
}
```

### 7.2 导出本地任务至 Google Calendar (`POST https://www.googleapis.com/...`)
如果用户在设置中开启了“允许同步新任务”，在本地新建任务或将某一常规任务成功确认编入日程时，支持向 Google 发送请求，创建对应的日程事件：

```javascript
async function exportTaskToGoogleCalendar(task) {
    const settings = DB.get('chrono_gcal_settings', {});
    if (!settings.enabled || !settings.autoExport || !settings.clientId) return;
    
    const token = DB.get('chrono_gcal_token');
    if (!token) return;
    
    const calId = encodeURIComponent(settings.exportCalendarId || 'primary');
    
    // 构建时间参数 (将 "2026-05-24" 和 "15:00" 拼接并生成正确的 ISO Date)
    const startIso = new Date(`${task.date}T${task.scheduledStart}:00`).toISOString();
    const endIso = new Date(`${task.date}T${task.scheduledEnd}:00`).toISOString();
    
    const eventBody = {
        'summary': `[ChronoAI] ${task.name}`,
        'description': `由 ChronoAI 自动排程。\n任务类别: ${task.category}\n预估时长: ${task.adjustedEstMins} 分钟。\n备注: ${task.notes || '无'}`,
        'start': { 'dateTime': startIso },
        'end': { 'dateTime': endIso },
        'colorId': task.category === 'work' ? '5' : (task.category === 'health' ? '10' : '7') // 根据分类选取 Google 日历颜色
    };
    
    try {
        const response = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${calId}/events`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(eventBody)
        });
        
        if (response.ok) {
            const data = await response.json();
            // 在本地任务中记录已导出的 gcalEventId，方便未来进行双向关联更新或链接跳转
            task.gcalEventId = data.id;
            console.log(`Task successfully exported to GCal. EventID: ${data.id}`);
        }
    } catch (e) {
        console.error('Failed to export task to Google Calendar:', e);
    }
}
```

***

## 8. Gap Finder 算法升级 (防日历冲突)

### 8.1 整合 Google Calendar 占用区间的 Gap Finder
升级后的算法将 `chrono_gcal_events_{date}` 中所有有效的 GCal 卡片自动注入 `occupied` （已占用）区间中，确保自动放置任务时绝对不会侵占任何工作会议或私人排程：

```javascript
function findBestGap(date, durationMins, preferAfter = null, externalTasksList = null) {
  // 1. 读取本地任务实例
  const localTasks = externalTasksList || loadTasks(date);
  const activeTasks = localTasks.filter(t => t.status !== 'skipped');
  
  // 2. 载入并并入 Google Calendar 日程实例
  const gcalSettings = DB.get('chrono_gcal_settings', {});
  let mergedOccupied = [];
  
  if (gcalSettings.enabled) {
      const gcalEvents = DB.get(`chrono_gcal_events_${date}`, []);
      // 将本地未跳过的任务与 Google Calendar 导入的任务合并
      mergedOccupied = [...activeTasks, ...gcalEvents];
  } else {
      mergedOccupied = [...activeTasks];
  }
  
  const workStart = 8 * 60;  // 08:00
  const workEnd = 22 * 60;   // 22:00
  
  // 3. 构建统一占用时间轴区间
  const occupied = mergedOccupied.map(t => ({
    start: timeToMins(t.scheduledStart),
    end: timeToMins(t.scheduledEnd)
  })).sort((a, b) => a.start - b.start);
  
  const scanFrom = preferAfter
    ? Math.max(timeToMins(preferAfter), workStart)
    : workStart;
    
  const gaps = [];
  let cursor = scanFrom;
  
  // 4. 计算空闲时间段 (Gap Slots)
  for (const busy of occupied) {
    if (busy.start > cursor) {
      gaps.push({ start: cursor, end: busy.start });
    }
    cursor = Math.max(cursor, busy.end);
  }
  if (cursor < workEnd) gaps.push({ start: cursor, end: workEnd });
  
  // 5. 寻找第一个符合预估时长的最优 Gap
  for (const gap of gaps) {
    if (gap.end - gap.start >= durationMins) {
      return {
        start: minsToTime(gap.start),
        end: minsToTime(gap.start + durationMins),
        reason: preferAfter
          ? `${minsToTime(gap.start)} 之后有连续 ${gap.end - gap.start}min 避让日历的黄金空档`
          : `避开日历的今日最早可用空档`
      };
    }
  }
  return null; // 无可用空档
}
```

***

## 9. 一键载入常规任务逻辑升级

在 v3.0 中，一键载入当天模板实例时，排程流程同样全面兼顾 Google Calendar：

```javascript
// 升级后的 Routine 日程分发流
function loadRoutinesForDate(date) {
  const routines = loadRoutines();
  const existing = loadTasks(date);
  const dayOfWeek = new Date(date).getDay();
  const isWeekday = dayOfWeek >= 1 && dayOfWeek <= 5;

  const applicable = routines.filter(r => {
    if (r.recurRule === 'daily') return true;
    if (r.recurRule === 'weekdays') return isWeekday;
    if (r.recurRule === 'weekly') {
      const createdDay = new Date(r.createdAt).getDay();
      return dayOfWeek === createdDay;
    }
    return false;
  });

  const newTasks = [];
  for (const routine of applicable) {
    // 检查是否已有同 routine 实例
    if (existing.some(t => t.routineId === routine.id)) continue;

    const adjustedMins = getAdjustedMins(routine);
    let placement;

    if (routine.preferredTime) {
      const prefStart = timeToMins(routine.preferredTime);
      const prefEnd = prefStart + adjustedMins;
      
      // 合并本地及 Google Calendar 缓存，进行全局碰撞检测
      const gcalEvents = DB.get(`chrono_gcal_events_${date}`, []);
      const allCurrentBlocks = [...existing, ...newTasks, ...gcalEvents];
      
      const conflict = allCurrentBlocks.some(t => {
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
        // 发生冲突（如 preferredTime 撞上 Google 会议），向后滑动寻找安全 Gap
        placement = findBestGap(date, adjustedMins, routine.preferredTime, [...existing, ...newTasks]);
      }
    } else {
      // 纯靠 Gap Finder 避开所有本地/Google 日历占用块
      placement = findBestGap(date, adjustedMins, null, [...existing, ...newTasks]);
    }

    if (!placement) continue; // 无空档抛弃

    const taskInstance = {
      id: `task_${date.replace(/-/g,'')}_${Date.now()}_${Math.random().toString(36).slice(2,6)}`,
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
    };
    
    newTasks.push(taskInstance);
    
    // 如果配置开启了 autoExport，静默将该常规实例同步写入 Google Calendar
    exportTaskToGoogleCalendar(taskInstance);
  }

  const merged = [...existing, ...newTasks];
  saveTasks(date, merged);
  return newTasks.length;
}
```

***

## 10. 视觉设计规范 (新增 GCal 专属样式)

### 10.1 毛玻璃锁定卡片特效
为了在极具视觉震撼力的深色毛玻璃主题中凸显 Google 日历的权威感与安全性，特设定如下 CSS 规范：

```css
/* Google Calendar 卡片风格 */
.task-card.gcal-locked {
    background: linear-gradient(135deg, rgba(66, 133, 244, 0.08) 0%, rgba(22, 22, 20, 0.7) 100%);
    border: 1px solid rgba(66, 133, 244, 0.25);
    box-shadow: 0 4px 20px rgba(66, 133, 244, 0.05);
    backdrop-filter: blur(12px);
    position: relative;
    overflow: hidden;
}

/* 装饰用淡光丝线效果 */
.task-card.gcal-locked::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 3px;
    height: 100%;
    background: linear-gradient(180deg, #4285f4, #34a853);
}

.gcal-lock-icon {
    font-size: 11px;
    color: rgba(66, 133, 244, 0.8);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: rgba(66, 133, 244, 0.15);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-weight: 500;
}

.gcal-open-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--text-muted);
    text-decoration: none;
    transition: color 0.2s ease;
    margin-top: 8px;
    width: fit-content;
}

.gcal-open-link:hover {
    color: #4285f4;
}
```

***

## 11. localStorage 工具函数升级配置

```javascript
// 在原有 DB 辅助工具中，扩展对 Google Calendar 相关键的获取
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

// 预设 Google 日历数据快捷助手
const loadGCalEvents = (date) => DB.get(`chrono_gcal_events_${date}`, []);
const saveGCalEvents = (date, data) => DB.set(`chrono_gcal_events_${date}`, data);
const getGCalSettings = () => DB.get('chrono_gcal_settings', {
    clientId: '',
    calendarId: 'primary',
    enabled: false,
    autoImport: true,
    autoExport: false,
    exportCalendarId: 'primary',
    lastSyncedAt: null
});
const saveGCalSettings = (settings) => DB.set('chrono_gcal_settings', settings);
```

***

## 12. 更新日志规范

在 `README.md` 中追加关于 Google Calendar 的迭代节点：

```markdown
### v3.0.0 — 2026-05-24
**修改文件**: index.html, plan.md  
**更新内容**:
- [NEW] 引入 Google OAuth 2.0 纯前端 GIS (Google Identity Services) 授权流。
- [NEW] 整合 Google Calendar API v3，支持拉取 Primary 日历日程进行本地渲染。
- [NEW] 时间轴呈现 GCal 锁定忙碌日程，并提供外部跳回日历编辑链接。
- [UPGRADE] Gap Finder 重构升级，在安排常规任务和 AI 拆解任务时，自动避让 Google 日历会期。
- [NEW] 支持 autoExport 机制，本地新增日程静默推至用户 Google Calendar 账户。
**当前状态**: ✅ 部署完毕，各项权限请求运行正常。
```

***

## 13. 验收测试清单

- [ ] **Client ID 存储校验**: Settings 中输入并保存 Client ID 后，刷新网页 `chrono_gcal_settings` 内容不丢失。
- [ ] **授权弹窗测试**: 点击 settings 中的“授权并连接 Google 日历”，能成功触发 Google Account 登录授权弹出窗。
- [ ] **Token 过期拦截**: 人为将 `chrono_gcal_expires_at` 设为 `0`，主时间轴自动呈现“黄色未授权/已过期”警示，点击能正确重连。
- [ ] **两网混合排序**: 模拟一个带有 2 个本地日程与 2 个 GCal 日程的日期，合并渲染后时间顺序完全正确（无倒序重叠）。
- [ ] **Gap Finder 避让会议**: 在 10:00 - 11:30 存在一个 GCal 日程的情况下，向 AI 发送指令“写代码一小时，不要给我定具体时间”，Gap Finder 算法将任务安插在 08:00 - 09:00 或 11:30 之后，绝不侵占会议时段。
- [ ] **一键分发防撞车**: 触发一键载入常规任务，某 PreferredTime 为 10:30 且耗时 30min 的常规模板刚好与 10:00 - 11:00 的 Google 周会冲突，该常规任务最终被自动顺延并排程在 11:00 之后。
- [ ] **锁卡只读机制**: GCal 类型的卡片上仅渲染 Google Calendar 信息与外部编辑超链接，无“开始/跳过”等交互，且不可任意从 timeline 中以本地删除键移去（如需更改，必须通过提供的外部链接回谷歌日历更改并重新同步）。
- [ ] **逆向静默写入**: 在开启 autoExport 的情况下，通过 AI 成功解析并确认添加一个本地任务后，调用 Network 控制台可见成功向 `googleapis.com` 发出 `POST` 创建 event 的网络请求。