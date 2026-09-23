# Loomi 私人入口迁移

这份流程保留现有记录、Firestore 数据和 Firebase UID。迁移只更换用户进入 Loomi 的方式。新入口由 Cloud Run 同时提供网页和 API；未登录者只能访问通行密钥登录页和公开健康检查。

当前状态（2026-09-24）：第二阶段已完成。手机端语音录入成功；Cloud Run 已设为仅通行密钥，Google 首次设置入口关闭，GitHub Pages 已停用。以下步骤保留作为部署与故障回退记录。

## 上线前

1. 确认 Cloud Run 当前部署服务、项目、服务账号和 `ALLOWED_FIREBASE_UID`。不要在配置或日志中输出私密环境变量的值。
2. Cloud Run 镜像必须用**仓库根目录作为构建上下文**，使用 `backend/Dockerfile`。镜像需要包含 `public/index.html`、`public/passkey-login.html`、`public/firebase-config.js`、`public/manifest.json`、`public/sw.js` 和 `public/loomi_icon.png`。
3. 确认 Cloud Run 服务账号可以读写当前 Firestore 项目。新入口的日常 API 请求直接验证服务端通行密钥会话，无需生成 Firebase 自定义令牌或授予服务账号签名权限。
4. 在 Firebase Authentication 的 Authorized domains 中加入新应用地址的主机名。本项目默认新地址为 `voice-assistant-1090997558704.europe-west2.run.app`。这只用于首次旧账号确认；通行密钥登录本身不依赖 Google 弹窗。
5. 配置 Firestore TTL：`loomi_auth_challenges.expires_at` 和 `loomi_auth_sessions.expires_at`。即使 TTL 删除有延迟，代码也会在读取时拒绝过期挑战和会话。

## 第一阶段：注册与验证

部署代码后，先设置：

```text
LOOMI_PASSKEY_ENABLED=true
LOOMI_PASSKEY_ONLY=false
LOOMI_SETUP_GOOGLE_ENABLED=true
LOOMI_PUBLIC_ORIGIN=https://voice-assistant-1090997558704.europe-west2.run.app
```

不要改变现有 `ALLOWED_FIREBASE_UID`、Firestore 或 API 密钥配置。此阶段旧 GitHub Pages 入口仍可使用，避免新入口故障时被锁在门外。

在需要使用 Loomi 的设备上访问 `/auth/setup`，用原账号确认身份并创建通行密钥。完成后访问 `/auth/login`，用设备屏幕锁登录。确认根页面打开、`/api/system/status` 在应用内成功、原有记录可读、录音可上传，并测试关闭浏览器后重新打开。建议在第二台设备或密码管理器中创建第二把通行密钥：从已登录的私人入口访问 `/auth/add-passkey`，系统会在添加前再次要求设备验证。

如果手机主屏幕上的旧 Loomi 图标指向 GitHub Pages，需要从新 Cloud Run 地址重新“添加到主屏幕”。旧图标不会自动改地址。

## 第二阶段：关掉旧登录入口

仅在第一阶段全部通过后切换：

```text
LOOMI_PASSKEY_ENABLED=true
LOOMI_PASSKEY_ONLY=true
LOOMI_SETUP_GOOGLE_ENABLED=false
```

验证无会话的 `/` 会跳到 `/auth/login`，无会话的 `/api/records` 返回 401；已经登录的新入口仍能读取、录音、上传。工作流密钥和 Notebook ingest 密钥的专用接口仍按原密钥工作。随后停用原 GitHub Pages 发布，并考虑将仓库设为 private；公开仓库中的前端源码即使页面停用仍可被浏览。GitHub Pages 旧域名上的本地浏览器数据不会自动迁往新域名，需要单独导出需要保留的本地日程。

Cloud Run `/health` 仍公开，只返回基本状态。新私有页面的会话 Cookie 为 `Secure`、`HttpOnly`、`SameSite=Lax`；闲置 90 天后需再次用通行密钥登录，期间每次打开应用会延长会话。主动退出会删除服务端会话。新入口的 API 使用通行密钥会话；第一阶段原 GitHub Pages 的 API 仍使用 Firebase UID，第二阶段只允许通行密钥会话。

## 故障回退

如果新入口验证失败，先保留旧 GitHub Pages。把 `LOOMI_PASSKEY_ONLY` 改回 `false` 并把 `LOOMI_SETUP_GOOGLE_ENABLED` 改回 `true`，现有 Google 认证 API 即可继续使用。不要删除 Firestore 中的 `loomi_passkeys`、`records` 或用户 UID。确认问题解决后，再重新执行第二阶段。
