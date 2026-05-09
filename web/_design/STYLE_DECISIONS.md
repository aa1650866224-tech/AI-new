# Web 前端样式决策

> 本项目 Web 看板（`web/index.html` + `style.css` + `app.js`）的设计语言基于 **Wired 印刷新闻日报范式**。
> 设计原型见同目录 `wired-DESIGN.md`（完整版 6000+ 字规范，未改一字）。
> 本文件记录"项目特异性决策"——也就是 Wired 通用规范在本项目落地时做的 5 个具体选择。
>
> **改样式之前请读这两份文件。** 不读会犯的最常见错误：把 verdict tag 配色改回饱和色块（破坏方案 B）、把 emoji 加回来（破坏方案 A）、给卡片加 box-shadow / border-radius（违反 Wired DNA）。

---

## 设计动机一句话

AI 新闻日报站 = **每日编辑过的资讯流**。Wired 是新闻日报范式里设计天花板，且 mono kicker / hairline rule / 编号列表三件事天然适配本项目"源标签 + 时间戳 + 编辑精选"的内容形态。其他 60+ 候选（Verge / Linear / PostHog / Resend / Cursor / opencode 等）在 2026-05-08 全量评估后筛除。

---

## 5 个核心参数（落地决策）

### 1. 字体替代方案

Wired 用的 4 套字体（WiredDisplay / BreveText / Apercu / WiredMono）全部为 Conde Nast 私有定制或商业授权字体，无法合法使用。本项目用 Wired DESIGN.md 第 90 行明确推荐的开源替代组合：

| 角色 | Wired 原字体 | 本项目替代品 | CJK 回退 |
|---|---|---|---|
| Display 衬体大字 | WiredDisplay | **Playfair Display** | 思源宋体 / Songti SC |
| Body 衬体阅读 | BreveText | **Source Serif 4** | 思源宋体 / Songti SC |
| UI 几何无衬 | Apercu | **Work Sans** | PingFang SC / 思源黑体 / Microsoft YaHei |
| Mono Kicker | WiredMono | **JetBrains Mono** | （ASCII only，不需要 CJK） |

字体加载在 `index.html` `<head>` 的 Google Fonts URL 里，CJK 走系统栈不下载。

**绝不要换成 Inter / Roboto / Arial / system-ui** —— Wired DESIGN.md 第 218 行明确禁止"generic AI-generated aesthetics"，那些字体会让整个页面瞬间退化成"普通 SaaS 落地页"。

---

### 2. GitHub Verdict 4 档配色：方案 B（Wired 蓝 + 3 克制次色）

Wired 主张「除 #057dbc 外禁止彩色」，但本项目有 4 档强语义 verdict tag（`true_use` / `hype_only` / `marketing` / `abandoned`）必须区分。最终方案：

```css
--verdict-true:       #057dbc;   /* Wired 蓝 — 真新方向（GO 含义） */
--verdict-hype:       #c8412b;   /* 砖红 — 编辑性 CAUTION */
--verdict-marketing:  #8a8a8a;   /* 静音灰 — 换皮，几乎"不值得喊"的视觉降级 */
--verdict-abandoned:  #1a1a1a;   /* 黑 + text-decoration: line-through — 弃坑 */
```

**为什么不用方案 A（纯黑白）**：辨识度太弱，4 档看起来都一样
**为什么不用方案 C（饱和色块）**：那就是 The Verge 不是 Wired 了

重要性 importance（`重磅` / `值得关注` / `了解即可`）也用同一克制色板：

```css
--imp-high: #c8412b;   /* 重磅 砖红 */
--imp-mid:  #1a1a1a;   /* 值得关注 黑 */
--imp-low:  #757575;   /* 了解即可 灰 */
```

---

### 3. 信息架构：顶部 ribbon tab（不是 sidebar）

源切换用**顶部全 bleed 黑色 ribbon tab**（`.source-ribbon`），sticky 跟随滚动。原因：
- Wired 没有 sidebar 范式
- 黑色 ribbon 是 Wired 标志性动作（"MOST POPULAR" / "GEAR" / "BACKCHANNEL" 全 bleed 黑条）
- 横向 7 个 tab 在桌面端铺满 ribbon，移动端横向滚动

**绝不要把 sidebar 改回来**——sidebar 是 SaaS dashboard 范式，会破坏"日报"气质。

---

### 4. Emoji 全部清除，改 mono caps

原版本用 🤖🐦🔴🚀🇨🇳🔶📋⭐🍴💬🔨📦 等 emoji 当 icon。Wired DESIGN.md 第 218 行禁止 emoji。本项目全部替换为 ALL CAPS mono 缩写：

| 原 emoji | 替换为 |
|---|---|
| 🐦 X | `X` |
| 🔶 HackerNews | `HACKER NEWS` |
| 🔴 Reddit | `REDDIT` |
| 🚀 ProductHunt | `PRODUCT HUNT` |
| 🐙 GitHub | `GITHUB` / `GH RADAR` |
| 🇨🇳 量子位 | `QBITAI` |
| 🟢 开发者真在用 | `TRUE USE` |
| 🟡 看的多用的少 | `HYPE ONLY` |
| 🔴 营销味重 | `MARKETING` |
| ⚫ 已停摆 | `ABANDONED` |
| ⭐ Star | `STAR` |
| 🍴 Fork | `FORK` |
| 💬 Issue | `ISSUE` |
| 🔨 Commit | `COMMIT` |
| 📦 Release | `RELEASE` |
| 📅 / 🔄 / 🔥 | `DATE` / `REFRESH` / `HEAT` |

后端 `verdict_label`（如 "🟢 开发者真在用"）**前端不再使用**——`app.js` 用前端常量 `VERDICT_META` 重新输出 mono 标签 + 双语 cn 名。后端字段保留兼容性。

**绝不要为了"友好"加回 emoji**——那一秒就把整个页面气质拽回 medium.com 博客模板。

---

### 5. 首页结构

```
┌─ utility-bar ──── DAILY · AI DIGEST · DATE · REFRESH ─────────┐
├─ masthead ────── AI 新闻日报（巨型 Playfair） ────────────────┤
│                  DAILY DIGEST · MULTI-SOURCE EDITORIAL FEED   │
│                  每日精选全球 AI 热门资讯（italic tagline）    │
├─ source-ribbon ─ DIGEST | GH RADAR | X | HN | RDT | PH | QBT ─┤  ← sticky
│                                                                │
│  ┌─ section-ribbon ── TOP STORIES · 每日精选 · 15 STORIES ──┐  │
│  │  page-desc：基于多源数据...（italic 灰字）                │  │
│  ├─ brief（仅 DIGEST 视图） ── TODAY'S BRIEF · 今日 AI 速览 ─┤  │
│  ├─ filter-bar ── CATEGORY · PRIORITY ────────────────────────┤  │
│  ├─ verdict-criteria（仅 GitHub 视图） 4 档判据卡 ───────────┤  │
│  ├─ story-list ─ 编号 01-15 + kicker + 衬体大标题 + deck + meta │
│  ├─ glossary（折叠） GitHub 术语小词典 ─────────────────────┤  │
│  └─ page-footer ── 黑底 mono caps ────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

详情页（`#detailView`）：mono kickers + 巨型衬体标题 + 原文标题（italic + 左 hairline）+ AI 摘要块 + verdict 块（仅 GitHub）+ 双语切换 + 详情 footer。

---

## 不可妥协的纪律（违反任何一条都会破坏 Wired DNA）

1. **`border-radius: 0`** —— 例外仅：圆形头像 (`50%`) / 文字 pill (`1920px`)
2. **0 `box-shadow`** —— 深度全靠 hairline rule
3. **颜色只能在 `style.css` `:root {...}` 里定义的 token 取用**——绝不在散落 CSS 写 `#xxx`
4. **mono 永远 ALL CAPS**，letter-spacing 0.9–1.2px——小写 mono 在 Wired 是 broken 状态
5. **emoji 永远不要回来**
6. **不要给 story-item 加 hover lift / scale / 阴影** ——hover 反应只允许：headline 文字色变 `--link-blue`
7. **不要给 ribbon tab 加 border-radius**——ribbon 是黑条，不是 pill

## 设计 token 入口

所有可调参数集中在 `web/style.css` 文件顶部 `:root { ... }` 块（约 30 行）。改色调、改字体、改间距，**先改 token，不要改散落的 hex/px**。

```css
:root {
    --ink-pure / --ink-page / --paper / --caption-gray / --hairline / --link-blue
    --verdict-true / --verdict-hype / --verdict-marketing / --verdict-abandoned
    --imp-high / --imp-mid / --imp-low
    --font-display / --font-body / --font-ui / --font-mono
    --gutter / --max-width
}
```

---

## 数据契约（前端假设的字段）

前端**严格按 `CLAUDE.md` 中定义的字段渲染**，不做兜底捏造：

- 所有源：`id` `title` `chinese_title` `chinese_summary` `chinese_content` `category` `sentiment` `heat_score` `author` `url` `source` `created_at`
- 非 GitHub：`importance ∈ {重磅, 值得关注, 了解即可}`
- GitHub：`verdict_tag ∈ {true_use, hype_only, marketing, abandoned}` + `verdict.{category_tag, who_should_care, prerequisites, similar_projects}` + `stars / forks / stars_today / github_meta`
- HackerNews：`discussion_url`（可选）

后端字段如增改，需同步更新 `app.js` 的 `renderStoryItem()` / `showDetailPage()` / `VERDICT_META` / `IMP_META`。

---

## 备份位置

重构前的原始版本在 `web/_backup_pre_wired/`（index.html / style.css / app.js）。如需对比"前 Wired 版"，看那里。
