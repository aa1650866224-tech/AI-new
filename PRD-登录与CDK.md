# PRD：登录与 CDK 兑换功能

> 状态：草案 v1（已经过新人视角审查，问题清单见 `PRD-登录与CDK-审查报告.md`）
> 关联项目：AI 新闻日报助手
> 目的：把网站从开放访问改造为付费会员制，作为咸鱼商品售卖。

---

## 1. 背景与目标

当前网站是 GitHub Pages 静态站点，免费访问。计划在咸鱼挂出销售：

- 用户下单后，卖家手动发送一个 **CDK（卡密）**
- 用户拿 CDK 在网站注册账号 → 获得 **30 天月卡**
- 到期后再买一个 CDK 续费

### 目标

1. 改造为登录可见，免费用户和过期用户看不到内容
2. 引入 CDK 兑换机制作为付费载体（一次性消耗）
3. 支持续费、多设备访问（PC + 手机）、密码找回
4. 在合理成本内防止数据被脚本批量爬取或多账号共用

### 非目标（本期不做）

- 在线支付（咸鱼线下结算，CDK 手动发）
- 邮件推送日报（已规划为二期）
- 内容水印 / 异常行为检测（视上线后情况再决定）
- CDK 管理后台（前期用命令行 + SQLite 客户端足够）

---

## 2. 用户流程

### 2.1 新用户注册（首次激活）

1. 在咸鱼下单，收到卖家发送的 CDK，格式 `XXXX-XXXX-XXXX-XXXX`
2. 访问网站 → 点击「注册」
3. 填写：邮箱、用户名、密码、CDK，一次性提交
4. 后端校验：CDK 有效且未使用、邮箱/用户名未被占用
5. 创建账号 → 标记 CDK 已用 → 设置 `expires_at = now + 30 days`
6. 自动登录，跳转首页

### 2.2 老用户登录

1. 邮箱/用户名 + 密码
2. 后端下发 session token，前端存 `localStorage`
3. 后续请求带 token，看到当日新闻

### 2.3 月卡到期续费

1. 用户访问网站，请求接口
2. 后端发现 `expires_at < now()` → 返回 401 + `code: EXPIRED`
3. 前端弹窗「会员已到期，请输入 CDK 续费」
4. 用户输入新 CDK 提交
5. 后端校验后：`expires_at = max(expires_at, now) + 30 天`
6. 关闭弹窗，恢复访问

### 2.4 找回密码

1. 登录页点击「忘记密码」→ 输入注册邮箱
2. 后端生成一次性 token，发邮件（QQ SMTP）
3. 用户点链接 → 设置新密码 → 跳转登录

### 2.5 多设备登录

- 同账号最多保持 **3 个有效 session**
- 第 4 次登录自动踢掉最久未活跃的那个
- 被踢的设备下次请求返回 401，自动跳登录页

---

## 3. 功能范围

### 一期（必做）

- [ ] 注册接口（邮箱 + 用户名 + 密码 + CDK）
- [ ] 登录接口（邮箱或用户名 + 密码）
- [ ] 续费接口（已登录用户输 CDK）
- [ ] 内容鉴权接口（数据走 API，不再静态托管）
- [ ] 找回密码（邮箱发重置链接）
- [ ] 登出接口
- [ ] 查看 / 踢掉自己的登录设备
- [ ] CDK 命令行生成工具
- [ ] 限频（账号 + IP 双维度）
- [ ] 多设备控制（最多 3 个 session）
- [ ] 部署到腾讯云
- [ ] 数据采集从 GitHub Actions 迁到服务器 crontab

### 二期（暂不做）

- 邮件推送日报
- 内容水印（出现转卖再做）
- 数据接口分页 / 按需加载（手机端体验不好再做）
- CDK 管理后台 Web 界面
- 到期前邮件提醒

---

## 4. 技术方案

### 4.1 技术栈

| 模块 | 选型 | 备注 |
|---|---|---|
| 后端框架 | Python + FastAPI | 与现有 `src/` 同语言，自带 OpenAPI |
| 服务器 | Uvicorn 单 worker | 单 worker 简化限频和内存计数 |
| 数据库 | SQLite | 用户量到千级前不会有压力 |
| 密码 | bcrypt（cost=12） | `passlib[bcrypt]` |
| Session | 数据库 token（不用 JWT）| JWT 无状态，做不了「踢下线」 |
| 邮件 | QQ 邮箱 SMTP | 免费、个人项目够用 |
| 反代 | Nginx | 同时托管前端静态文件 |
| 证书 | Let's Encrypt | 免费、自动续期 |
| 数据采集 | crontab | 替代 GitHub Actions |

### 4.2 整体架构

```
[浏览器]
   ↓ HTTPS
[Nginx :443]
   ├─ /api/*  → [FastAPI :8000]   (鉴权 + 数据接口)
   └─ /*      → 静态文件 (index/login/register/reset.html, app.js, css)

[FastAPI] ←→ [SQLite]  (users, cdks, sessions, password_resets)
[FastAPI] ──读取──→ [data/daily/*.json]

[crontab 09:00] → python src/main.py → 写 data/daily/*.json
```

### 4.3 数据库设计

```sql
-- 用户表
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,           -- bcrypt
  expires_at DATETIME NOT NULL,          -- 月卡到期时间
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CDK 表
CREATE TABLE cdks (
  code TEXT PRIMARY KEY,                 -- 16 位 base32 + 分隔符
  duration_days INTEGER NOT NULL DEFAULT 30,
  used INTEGER NOT NULL DEFAULT 0,       -- 0=未用 1=已用
  used_by_user_id INTEGER,
  used_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (used_by_user_id) REFERENCES users(id)
);

-- Session 表（多设备控制 + 主动登出）
CREATE TABLE sessions (
  token TEXT PRIMARY KEY,                -- secrets.token_urlsafe(32)
  user_id INTEGER NOT NULL,
  user_agent TEXT,
  ip TEXT,
  last_active_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_sessions_user ON sessions(user_id, last_active_at);

-- 密码重置 token
CREATE TABLE password_resets (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at DATETIME NOT NULL,          -- 30 分钟有效
  used INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### 4.4 API 设计

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/auth/register` | 无 | 注册 + 兑换 CDK |
| POST | `/api/auth/login` | 无 | 登录 |
| POST | `/api/auth/logout` | 是 | 删除当前 session |
| POST | `/api/auth/redeem` | 是 | 续费（已登录用户输新 CDK） |
| POST | `/api/auth/password-reset/request` | 无 | 申请重置邮件 |
| POST | `/api/auth/password-reset/confirm` | 无 | 用 token 设新密码 |
| GET  | `/api/me` | 是 | 当前用户信息 + 到期时间 |
| GET  | `/api/me/sessions` | 是 | 自己的所有登录设备 |
| DELETE | `/api/me/sessions/{token}` | 是 | 踢掉某个设备 |
| GET  | `/api/daily/index` | 是 | 列出可选日期 |
| GET  | `/api/daily/{date}` | 是 | 取指定日报数据 |

### 4.5 关键实现细节

#### CDK 格式
- **16 位 base32**（A-Z + 2-7，去掉易混的 0/1/I/O），分组 `XXXX-XXXX-XXXX-XXXX`
- 字符空间约 2^80，安全
- 命令行工具：`python tools/gen_cdk.py --count 50 --days 30 > cdks_2026-05.txt`

#### CDK 兑换原子性（防并发）
```sql
UPDATE cdks SET used=1, used_by_user_id=?, used_at=CURRENT_TIMESTAMP
WHERE code=? AND used=0
```
检查 `cursor.rowcount == 1` 才算兑换成功。绝不能「先 SELECT 再 UPDATE」。

#### 续费时间计算
```python
new_expires = max(user.expires_at, now()) + timedelta(days=cdk.duration_days)
```
未过期续费在原到期日上加，已过期续费从今天起算。

#### Session 生成与清理
```python
# 登录成功
token = secrets.token_urlsafe(32)
db.insert(sessions, user_id=u.id, token=token, ...)

# 控制最多 3 个
rows = db.query(
  "SELECT token FROM sessions WHERE user_id=? ORDER BY last_active_at ASC", u.id)
while len(rows) > 3:
    db.execute("DELETE FROM sessions WHERE token=?", rows.pop(0).token)
```

#### 限频
| 维度 | 接口 | 阈值 |
|---|---|---|
| 账号 | 所有数据接口 | 60/分、1000/时 |
| IP | `/auth/register`、`/auth/login`、`/password-reset/request` | 5/分 |

实现：进程内字典 `{key: deque[timestamps]}`，单 worker 部署不需要 Redis。

#### 邮件发送
- QQ 邮箱开启 SMTP，使用「授权码」而非密码
- 配置项：`SMTP_HOST=smtp.qq.com`、`SMTP_PORT=465`、`SMTP_USER`、`SMTP_PASSWORD`
- 单封邮件 < 1KB，QQ 个人邮箱日发送量足够支撑小项目

### 4.6 前端改造

新增页面：
- `web/login.html`
- `web/register.html`
- `web/reset.html`（含申请 + 设置新密码两个状态）

`web/app.js` 改动点（共 2 处 fetch）：
```js
// 改前
const resp = await fetch('data/index.json');
const resp = await fetch(`data/${dateStr}.json`);

// 改后
const token = localStorage.getItem('token');
const headers = { Authorization: `Bearer ${token}` };
const resp = await fetch('/api/daily/index', { headers });
const resp = await fetch(`/api/daily/${dateStr}`, { headers });

// 拦截 401：
//   code === 'EXPIRED' → 弹续费框
//   code === 'UNAUTH'  → 跳登录页
```

---

## 5. 防爬与风控

### 5.1 一期实施（必做）

| # | 措施 | 实现 |
|---|---|---|
| 1 | 架构鉴权 | 数据走 API，所有接口要求 session token |
| 2 | 账号级限频 | 60/分、1000/时 |
| 3 | IP 级限频 | 注册/登录 5/分，防爆破 |
| 4 | 多设备控制 | 同账号最多 3 个 session |

### 5.2 二期视情况启动

- **内容水印**：零宽字符编码用户 ID。注意：对截图转卖无效，仅对原文转卖有威慑
- **异常行为检测**：连续高频访问临时封号

### 5.3 不做

- 前端加密 / 请求签名（前端代码可见，绕不掉）
- 设备指纹（与多设备需求矛盾）
- 图形验证码（体验差，新闻场景没必要）

### 5.4 商业层反思

新闻数据本身是 X / HN / Reddit 的公开信息，用户付费买的是「汇总 + 翻译 + AI 摘要」的便利。理论上想白嫖的人完全可以付一次月卡费、自己爬一份重卖。**防爬投入的合理上限 = 月卡价 × 预估盗用率**，不应过度投入。一期做到「让脚本明显不便」即可。

---

## 6. 部署方案

### 6.1 服务器

- 腾讯云**轻量应用服务器**
- **2 核 2G 起步**（1G 大概率 OOM：FastAPI + Nginx + 数据采集 trafilatura + LLM 调用）
- 系统：Ubuntu 22.04
- 地域：广州 / 上海（国内访问快）

### 6.2 域名

- **必须备案**（国内服务器 + 国内访问）
- 备案周期 7-20 天，需提前办理
- 备案期间可用 IP 临时访问，或选香港机房（不用备案但延迟稍高）

### 6.3 部署清单

1. Nginx 装好，配置 80/443，反代 `/api/*` 到 FastAPI（127.0.0.1:8000）
2. Let's Encrypt 自动证书（`certbot --nginx`）
3. systemd service 管理 FastAPI 进程（开机自启 + 崩溃自重启）
4. crontab 每天 01:00 UTC（北京 09:00）跑 `python src/main.py`
5. SQLite 每天定时备份：`cp app.db backups/app-$(date +%F).db`，保留 30 天
6. `.env` 文件配齐所有 API key（DEEPSEEK / X / GH / SMTP 等）
7. 数据采集失败时发邮件告警给卖家自己

### 6.4 数据采集迁移

- 停用 `.github/workflows/daily-digest.yml`
- crontab 替代：`0 1 * * * cd /opt/app && /opt/app/venv/bin/python src/main.py >> logs/cron.log 2>&1`
- 输出仍写 `data/daily/*.json`，FastAPI 直接读这个目录

---

## 7. 风险与权衡

| 风险 | 影响 | 应对 |
|---|---|---|
| 域名备案未过 | 网站无法访问 | 提前备案；过渡期可用 IP 或香港机房 |
| 单天 JSON 近 1MB | 移动端 4G 慢 1-2 秒 | 一期接受；二期做按需加载 |
| 用户截图转卖 | 收入损失 | 一期不防；视情况上水印 |
| 多账号共用 | 收入损失 | 3 设备上限缓解，水印兜底 |
| QQ SMTP 限量 | 邮件发不出 | 个人项目量小不会触发；超限再换 SendGrid |
| SQLite 并发瓶颈 | 高并发卡 | 用户上千才会遇到 |
| crontab 跑失败 | 当天无新数据 | 失败发邮件给自己 |
| 用户 30 天忘记续费 | 流失 | 二期做到期前邮件提醒 |

---

## 8. 里程碑（参考）

| 阶段 | 内容 | 预估 |
|---|---|---|
| M1 | FastAPI 骨架 + 用户/CDK/session 表 + 注册登录 API | 2 天 |
| M2 | 续费 + 找回密码 + 多设备控制 + 限频 | 2 天 |
| M3 | 前端改造（登录/注册/重置页 + fetch 适配） | 2 天 |
| M4 | CDK 生成工具 + 邮件发送联调 | 1 天 |
| M5 | 部署腾讯云 + 数据采集迁移 | 1-2 天 |
| M6 | 端到端联调 + 上线 | 1 天 |
| **合计** | | **9-10 天 + 备案等待时间** |

---

## 9. 待办 / 需要确认的事

- [ ] 域名是否已备案？（不影响开发，但影响上线时间）
- [ ] 腾讯云服务器是否要现在下单？建议看完 PRD 再买
- [ ] 月卡定价多少？（影响"防爬投入合理上限"判断）
- [ ] CDK 一次生成多少个备货？（影响命令行工具默认参数）
- [ ] 注册时密码强度要求？建议最低 8 位 + 字母 + 数字
- [ ] 是否需要"测试 CDK"？（自己测试用、或给少数人试看）

---

## 10. 已确认的关键决策（讨论纪要）

1. **架构必须改**：纯静态前端拦不住爬虫，数据接口必须后端鉴权
2. **CDK 是消耗品**：一次性使用，注册时一并提交（账号 + 密码 + CDK）
3. **月卡 30 天**，从兑换那一刻起算
4. **续费**：老用户输入新 CDK 在原到期时间上加 30 天
5. **多设备**：允许，限制最多 3 个同时在线
6. **过期账号保留**：不删除，再续费即可恢复
7. **必填邮箱**：用于密码找回 + 二期邮件推送
8. **不做注册时邮箱验证**：付费用户乱填邮箱的成本由其自负
9. **使用 QQ 邮箱 SMTP**
10. **用 session token 而非 JWT**：JWT 无状态，做不了「踢下线」
11. **单 worker + 内存限频**：腾讯云 1G 内存装 Redis 不划算
12. **2H2G 起步**：1G 跑数据采集会 OOM
