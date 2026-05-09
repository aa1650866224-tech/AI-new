# PRD 审查报告（v1）

> 审查方式：以新人视角对照实际代码逐项验证 PRD 中的声称
> 关联文档：`PRD-登录与CDK.md`
> 输出由子 agent 生成，未做改动

---

## TL;DR

**需要中等修订才能开工**，方案大方向合理但落地细节漏洞较多。最关键的 3 个问题：

1. 注册流程涉及 CDK 标记 + 用户创建 + session 三步操作但 PRD 只给了"防并发 UPDATE"模板，没说事务边界
2. `web/data/` 与 `data/daily/` 镜像逻辑迁移后将出现"双源真相"且 PRD 完全没提
3. M1-M6 共 9-10 天对一个含部署 + 备案 + 邮件联调的全栈改造严重低估

---

## 阻塞级问题（必须解决才能开工）

### [阻塞] 注册流程缺少事务边界定义
- **现象**：PRD §4.5 给了"防并发"的 SQL 模板（`UPDATE cdks ... WHERE used=0`），但注册流程要做 3 步：兑换 CDK、INSERT users、INSERT sessions。中间任何一步失败的回滚策略 PRD 没写。
- **为什么是问题**：CDK 兑换成功但 INSERT users 因唯一约束冲突失败，CDK 就被烧掉了——用户钱花了账号没建。
- **验证**：PRD 第 201-206 行只示范了单个 UPDATE 语句。
- **修复方向**：明确"先 INSERT user → 拿到 user_id → UPDATE cdk SET used_by_user_id=user_id WHERE used=0 → rowcount==0 时 ROLLBACK 整个事务"。SQLite 默认 autocommit，必须显式 `BEGIN IMMEDIATE`。

### [阻塞] 数据目录"双源真相"未澄清
- **现象**：PRD §4.2 架构图写「FastAPI ──读取──→ data/daily/*.json」，但 `src/main.py` 第 173-186 行还在执行 `copy_to_web()` + 重建 `web/data/index.json`；`scripts/build_index.py` 也只重建 `web/data/index.json`。
- **为什么是问题**：迁移到服务器后，FastAPI 到底读哪个目录？两份 JSON 是否同步？同时存在的话，备份哪一份？磁盘占用翻倍（实测 `data/daily` 已 ~3MB，会持续增长）。
- **验证**：`src/storage/json_storage.py` 第 34-45 行 `copy_to_web()`，`src/main.py` 第 173-186 行；`scripts/build_index.py` 实际写入路径。
- **修复方向**：明确决策——保留 `data/daily/` 作单一事实源、删除 `copy_to_web()` 调用与 `scripts/build_index.py`，改由 FastAPI 的 `/api/daily/index` 实时 glob 目录。否则保留现状但 PRD 应说明双写理由。

### [阻塞] 数据采集与 Web 进程对 SQLite 的并发未定义
- **现象**：PRD §6.3 写"每天 01:00 跑数据采集，每天定时备份 SQLite"。
- **为什么是问题**：备份执行 `cp app.db backups/...` 时如果 Web 正在 INSERT session，可能复制出半写状态文件。SQLite 默认 journal mode 不是 WAL，写时整库锁，备份得到的文件可能损坏。
- **验证**：`requirements.txt` 第 1-6 行无 sqlite 配置；PRD §6 整节没提 journal mode。
- **修复方向**：明确启用 WAL（`PRAGMA journal_mode=WAL`），备份用 `sqlite3 .backup` 命令而非 `cp`。

---

## 严重问题（开工后会卡）

### [严重] PRD 时间估算严重低估
- **现象**：M1-M6 共 9-10 天。
- **为什么是问题**：M5「部署腾讯云 + 数据采集迁移」给 1-2 天，但还要装 Nginx、配 Let's Encrypt、写 systemd、备案、SMTP 联调（QQ 邮箱授权码 + 端口被云厂商封 25 是常见坑）、把 `.env` 里 4-5 个 API key 全部迁好。M3「前端改造」2 天里要新增 3 个 HTML 页面 + 401 拦截 + token 续签 + UI 适配，按现在 `web/app.js` 845 行的复杂度看至少 3 天。
- **修复方向**：M3 改 3 天、M5 改 3 天，整体改 12-14 天 + 备案。

### [严重] `cdks.used` 字段缺索引
- **现象**：PRD §4.3 SQL 只对 `sessions(user_id, last_active_at)` 建了索引。
- **为什么是问题**：兑换 CDK 时 `WHERE code=?` 走主键 OK，但管理脚本 `SELECT * FROM cdks WHERE used=0` 会全表扫。CDK 上千条后慢。
- **修复方向**：补 `CREATE INDEX idx_cdks_used ON cdks(used) WHERE used=0;`（部分索引更省）。

### [严重] SQLite 外键默认关闭，PRD 未提
- **现象**：表里写了 `FOREIGN KEY (used_by_user_id) REFERENCES users(id)` 但 SQLite 默认 `foreign_keys=OFF`。
- **为什么是问题**：写了形同未写，删除 user 时 cdks/sessions 不会级联，会留孤儿数据。
- **修复方向**：启动连接时显式 `PRAGMA foreign_keys = ON`，并在 FK 上加 `ON DELETE CASCADE`/`SET NULL`。

### [严重] 限频字典内存泄漏
- **现象**：PRD §4.5「进程内字典 `{key: deque[timestamps]}`」。
- **为什么是问题**：没说什么时候清理 key。一年内成千上万 IP 访问后字典无限增长，单 worker 内存撑不住。
- **修复方向**：定时任务（如每 5 分钟）扫描所有 key，丢弃 deque 已全部过期的条目。

### [严重] 账号枚举漏洞
- **现象**：PRD 没规定"邮箱不存在"和"密码错误"的统一响应。注册接口若返回"邮箱已注册"，攻击者可枚举用户邮箱。
- **修复方向**：找回密码不论邮箱是否存在都返回"邮件已发送（如该邮箱已注册）"；注册时邮箱重复也只返回模糊错误码。

### [严重] 续费无上限
- **现象**：PRD §4.5 续费公式 `new_expires = max(expires, now) + 30天`。
- **为什么是问题**：黑产囤 100 个 CDK 一次性续，到期时间叠到 8 年后。一旦泄露/转卖损失大。
- **修复方向**：限制 `expires_at <= now + 90 天`，超出拒绝。

---

## 一般问题

### [一般] PRD 单天 JSON 大小估错
- **现象**：PRD §7 写「单天 JSON 近 1MB（500-700KB 平均，最大 880KB）」。
- **验证**：实测 `web/data/2026-05-05.json` = **905,612 字节 (884KB)**，已贴近 1MB。
- **修复方向**：M3 阶段就上 gzip 响应（Nginx 配 `gzip on`），把 880KB 压到 ~150KB。

### [一般] 邮件发送是同步还是异步未定义
- **现象**：PRD §2.4 找回密码"生成 token 发邮件"。
- **为什么是问题**：QQ SMTP 偶尔卡 5-10 秒，同步等会让接口超时。
- **修复方向**：用 FastAPI BackgroundTasks 异步发，接口立即返回成功。

### [一般] Session 被踢逻辑可被并发绕过
- **现象**：PRD §4.5 先 SELECT 再 DELETE，循环到 ≤3。
- **为什么是问题**：用户在两个浏览器同时登录，两个请求都查到 3 条，都判定"无需踢"，落地 4 条。
- **修复方向**：INSERT 后用 `DELETE FROM sessions WHERE user_id=? AND token NOT IN (SELECT token FROM sessions WHERE user_id=? ORDER BY last_active_at DESC LIMIT 3)` 一条 SQL 保证。

### [一般] `password_resets` 过期清理无人负责
- **现象**：PRD 表设计有 `expires_at` 但没说谁清理。
- **修复方向**：crontab 加每日 `DELETE FROM password_resets WHERE expires_at < now()`。

### [一般] 25/465 端口被云厂商封锁
- **现象**：腾讯云轻量服务器默认封 25/465 出方向，PRD §4.5 直接用 `SMTP_PORT=465`。
- **修复方向**：上线前需先工单申请解封，或改用 587 + STARTTLS。

---

## 建议（锦上添花）

### [建议] FastAPI 启动失败 / 数据采集失败用同一套告警
- 目前 PRD §6.3 第 7 条只提"采集失败发邮件"，但 systemd 崩溃没说怎么发现。建议统一到 systemd `OnFailure=` 钩子。

### [建议] 引入登录失败次数锁定
- PRD 只对 IP 做了 5/分钟限频。同 IP 用 5 个用户名各试 1 次密码就绕过。建议 `users` 表加 `failed_login_count` + `locked_until` 字段。

---

## 与代码不符的地方

| PRD 描述 | 实际情况 | 文件位置 |
|---|---|---|
| "单天 JSON 平均 500-700KB，最大 880KB" | 最大 905KB（贴近 1MB） | `web/data/2026-05-05.json` |
| §6.4 "停用 daily-digest.yml" | yml 还做了 commit 回仓库 + 部署 GitHub Pages 两件事 PRD 没提，迁移后这两件事都消失，需明确 | `.github/workflows/daily-digest.yml` 第 49-67 行 |
| §4.2 架构图 FastAPI 直接读 `data/daily/*.json` | 现 `main.py` 同时写 `data/daily/` 和 `web/data/`，迁移后需删 `copy_to_web()` 与 `build_index.py` | `src/main.py` 第 173-186 行；`scripts/build_index.py` |
| §4.6 "app.js 共 2 处 fetch" | 验证属实 | `web/app.js` 第 91、103 行 |
| §6.3 ".env 配齐 API key" | 实际现有 4 个 key（DEEPSEEK / X / GH_PAT / PRODUCTHUNT），PRD 还要新增 SMTP 4 个 + JWT secret 等，未列清单 | `config/settings.yaml` |

---

## 漏掉的重要场景

1. **用户主动注销账号**：PRD 全程没提。一旦法规要求支持注销，cdks / sessions 怎么处理？
2. **CDK 退款 / 作废**：用户买了 CDK 没用就要求退款，运营怎么标记 CDK 失效？需要 `revoked` 字段。
3. **时区**：crontab `0 1 * * *` 是 UTC 还是服务器时区？腾讯云 Ubuntu 默认 UTC，PRD §6.3 写"01:00 UTC（北京 09:00）"但 ubuntu 默认 `timedatectl` 不一定是 UTC。需要明确 `TZ=Asia/Shanghai` 或调整 cron 时间。
4. **CSRF**：API 用 Bearer token 存 localStorage 通常不受 CSRF 影响，但 PRD 没显式说明。如果误用 cookie 就漏了。
5. **HTTPS 强制**：PRD §6.3 装了证书但没说 HTTP→HTTPS 跳转规则。session token 经 HTTP 传递就泄露。
6. **数据采集失败时旧数据怎么对外**：crontab 跑挂了，FastAPI 接口拿到的是昨天数据还是 404？前端如何区分？
7. **首次部署"鸡生蛋"**：服务器上 `.env` 怎么传？SQLite 初始化脚本谁跑？PRD §6 缺一份"裸机到上线"的脚本清单。
8. **前端 token 何时清理**：登出 / 账号过期 / 被踢，三种场景前端 localStorage 怎么处理 PRD 未规范。
9. **`PRODUCTHUNT_TOKEN` 在 PRD 表里被遗漏**（CLAUDE.md 列出，PRD §6.3 第 6 条只笼统说"API key"）。
