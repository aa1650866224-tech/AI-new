# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI 新闻日报助手：每日从 Hacker News / Reddit / RSS（量子位 + OpenAI/DeepMind/4 个一线开发者 blog 等 7 源）/ GitHub Trending / HuggingFace Trending Models 多源采集 AI 资讯，经评分、去重、抓取正文、翻译、AI 摘要后，输出 JSON 日报和静态 Web 看板。本地手动运行 `python src/main.py` 触发全流程。

输出形态：**4 板块 tab**（今早必读 / 圈子在吵 / GitHub 雷达 / 周末再看），每条带 80-120 字 LLM 编辑按语（`editor_note`）。**v2 架构已砍除"综合精选 Top 15"和 `importance` 字段**——读者自己挑，不让 LLM 替读者排序。

设计文档：
- 设计：`docs/superpowers/specs/2026-05-08-数据源重构-design.md`
- 实施计划：`docs/superpowers/plans/2026-05-08-数据源重构.md`

待接入（依赖外部基础设施）：
- **RSSHub** 路由：X 白名单（30 大 V）+ Anthropic / Meta AI / 机器之心（这 3 家无官方 RSS）。需本地 Docker 部署 RSSHub 后接入。
- **Firecrawl**：DeepSeek / 智谱 / Kimi / 通义国内厂商博客（SPA 站点）+ 网信办 / EU AI Act / White House AI EO 政策站。需 `FIRECRAWL_API_KEY`。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 跑一次完整流程（采集 + 摘要 + 写入 data/daily/YYYY-MM-DD.json 和 web/data/）
python src/main.py

# 本地预览看板（必须用 http server，file:// 加载 JSON 会被浏览器拦）
cd web && python -m http.server 8080
# 或直接双击根目录的"启动网页.bat"
```

无测试套件、无 lint 配置；所有验证靠 smoke test（每个 collector / processor 改完单独跑一次确认有数据 + 端到端跑一遍 main.py）。

## 环境变量

`src/main.py` 启动时通过 `python-dotenv` 自动加载项目根目录的 `.env`。

| 变量 | 用途 | 状态 |
|---|---|---|
| `DEEPSEEK_API_KEY` | AI 摘要 + 翻译，所有 LLM 调用都走 DeepSeek | **必需** |
| `GH_PAT` | GitHub API 限流提升（用于采集 GitHub Trending） | 可选 |
| `FIRECRAWL_API_KEY` | Firecrawl 抓取国内厂商博客 + 政策站 | **待启用**（Phase 5 收尾时填） |

`config/settings.yaml` 中的 `${VAR}` 语法**不会**被自动展开——代码在每个 collector / processor 内部单独 `os.getenv(...)`，YAML 里的占位符仅作文档用途。

## 整体流水线（src/main.py）

`main()` 是一条线性管道，理解这个顺序对改任何环节都关键：

1. **采集**：5 个 collector 串行调用，**单个源失败不影响其他源**（每个 collector 套 `try/except`）。collector 优先尝试 `fetch(keywords_config=...)`，不支持则 `TypeError` 回退到 `fetch()`——新增 collector 时两种签名都可以。
2. **URL 去重** (`processors/dedup.py::url_dedup`)：在评分前做，归一化掉 `www.` 和尾部斜杠。
3. **热度评分** (`processors/ranker.py`)：likes / retweets / replies / stars / forks 加权求和，大 V (`author_followers >= follower_threshold`) 加成，超过 `decay_hours` 后线性衰减。所有时间统一转 UTC aware datetime。
4. **正文抓取** (`processors/article_fetcher.py::enrich_items`)：用 `trafilatura` 抓外链正文，按 URL 哈希缓存到本地。**域名分流**：`SKIP_DOMAINS`（reddit / youtube / medium 等）跳过；arxiv 走官方 API 拿 abstract；GitHub 仓库走 GitHub API 拿 README，结果存到临时字段 `_readme_hint`。
5. **GitHub 避坑判定** (`processors/github_verdict.py::annotate`)：在翻译前跑，因为 verdict_tag 要进 summarize prompt。先用 `github_snapshot.load_recent_snapshots()` 读最近 7 天 `data/github_snapshots.jsonl` 历史，然后按规则给每个 trending 仓库打 4 选 1 标签：`abandoned` / `marketing` / `hype_only` / `true_use`。release（`id` 以 `gh_rel_` 开头）跳过。判据细节见 `github_verdict.py` 头注释。
6. **翻译分级** (`processors/translator.py`)：英文正文翻译为中文，写入 `chinese_content`。
   - **DEEP**（厂商博客 / 个人 blog / 中文媒体）：全文翻译，长文分段
   - **SHALLOW**（HN / Reddit / X）：截断到前 200 字再翻译，节约 token（讨论类原文链接为主）
   - **SKIP**（GitHub / HuggingFace）：仓库类不翻译
   翻译前会把图片 Markdown `![](...)` mask 成占位符，避免 LLM 改坏 URL。
7. **板块映射** (`processors/section_mapper.py`)：按 `source` 给每条打 `section ∈ {morning, discussion, github, weekend}`。`_section_hint` 临时字段（如 HF collector 设置的 `weekend`）优先级高于 source 查表。
8. **板块切分 + cap**：`split_by_section()` 按 heat_score 降序切，`morning ≤ 8`、`discussion ≤ 10`、`github / weekend` 不限——cap 之外的条目丢弃，**不再进入 AI 摘要**（节约 LLM token）。
9. **AI 摘要** (`processors/summarize.py`)：对板块切分后的所有 items 摘要。**GitHub 源走专属祛魅 prompt** `summarize_github_repo()`（基于 `_readme_hint` + `verdict_tag` 输出 `verdict.{category_tag, who_should_care, prerequisites, similar_projects}`，**不输出 `importance` / `repo_card`**），其他源走通用 `summarize_item()`（输出含 80-120 字 `editor_note` 编辑按语）。`process_batch` 末尾全局清场所有 `importance` 字段（v2 架构不再使用）。
10. **GitHub 雷达 7 天滚动** (`processors/github_aggregate.py`)：摘要后用 `aggregate_7days()` 把今日 GitHub trending 与最近 6 天累积存档（`data/github_radar.jsonl`）合并去重，按 verdict_tag 分组、组内按 heat_score 降序、每档限 20 条；release 不累积。然后 `append_today()` 把今日 trending 写入存档，`prune_old(max_days=14)` 清理超期。结果**覆盖 `by_section["github"]`**。**独立存档而非读历史 daily JSON**——因为 verdict 阈值升级后，历史 daily 里旧标签和新规则混用会污染雷达；调阈值时清掉 jsonl 即可重建。
11. **日报总览**：`summarizer.daily_overview()` 用 LLM 生成 200 字"今日 AI 速览"，素材池 = `morning + discussion` 前 10 条。
12. **存储**：`storage/json_storage.py` 写 `data/daily/YYYY-MM-DD.json`，再 `copy_to_web()` 同步到 `web/data/`，最后用 glob 重建 `web/data/index.json`（前端用它列出可选日期）。
13. **GitHub 历史快照**：`github_snapshot.append_today_snapshot()` 把今日 trending 仓库（仅 stars/forks/issues/pushed_at）追加到 `data/github_snapshots.jsonl`，供下次运行时步骤 5 读取；`prune_old_snapshots(max_days=90)` 清理 90 天前。release 不存。

## 数据契约

LLM 输出的字段是前端和后续处理的硬约束，改 prompt 时必须保留：

**通用字段**（所有源）
- `category` ∈ {`模型发布`, `产品更新`, `技术论文`, `行业观点`, `投资融资`, `开源工具`}——前端筛选用
- `chinese_title` / `chinese_summary` / `original_excerpt` / `sentiment`
- `editor_note` —— 80-120 字的中文编辑按语（v2 新增），前端在卡片上以 pull-quote 形式渲染（"编者按 —" 前缀）
- `section` ∈ {`morning`, `discussion`, `github`, `weekend`} —— 板块归属，由 `section_mapper` 写入

**GitHub 源**
- 规则引擎写入：`verdict_tag` ∈ {`true_use`, `hype_only`, `marketing`, `abandoned`}，附带 `verdict_label` / `verdict_explain` / `verdict_analogy`（前端展示文案，元信息见 `github_verdict.py::VERDICT_META`）
- LLM 写入：`verdict.{category_tag, who_should_care, prerequisites, similar_projects}`，其中 `category_tag` ∈ {`真新方向`, `老问题的新工具`, `换皮再卷一遍`, `Demo 级想法`}；`similar_projects` 允许是空数组（**严禁 LLM 编造**）
- 雷达累积条目额外有 `radar_date` 字段
- ⚠️ GitHub 源**不写 `editor_note`**（用 verdict 体系替代）、**不写 `importance`**

**已弃字段（v1 → v2 砍除）**：
- `importance` ∈ {`重磅`, `值得关注`, `了解即可`} —— v1 用于综合精选分层，v2 砍除"综合精选 Top 15"后该字段失去意义。`summarize.process_batch` 末尾会全局 pop。
- `repo_card` —— v1 GitHub 项目卡片，v2 已被 verdict 体系替代

每日 JSON 顶层结构：`{date, generated_at, overview, by_section: { morning, discussion, github, weekend }}`。**不再有 `items` / `by_source` / `count` 字段**。

`processors/dedup.py::cluster_dedup` 用硬编码关键词列表做粗聚类，**目前 main.py 没调用它**，只用了 `url_dedup`。如果发现"重复事件刷屏"想启用，记得在评分后插入。

## 配置与持久化文件

- `config/settings.yaml`：DeepSeek API 配置、各源阈值（HN `min_score` / `min_comments`、Reddit `subreddits` 列表、GitHub `trending_count` 等）、HuggingFace 排序方式、`sections.morning_max` / `discussion_max` 板块容量、热度评分权重、Firecrawl 目标列表（待启用，URL 多为 `TBD`）。
- `config/keywords.yaml`：`include` 用于 HN / Reddit 等 collector 内部过滤抓取内容，`exclude` 用于屏蔽抽奖 / 加密币 / web3 等噪声。会被 `main.py` 注入到 `config["keywords"]` 透传给 collector。
- `data/daily/YYYY-MM-DD.json` 与 `data/article_cache/`、`data/*.jsonl` 都已加入 `.gitignore`（运行时产物，每个开发机不同）。
- `web/data/YYYY-MM-DD.json`：前端读取的拷贝，**仍跟踪在 git 里**（让 clone 后能看到示例）。`web/data/_archive/` 为旧结构（v1 by_source）的归档，前端不读。
- `data/github_snapshots.jsonl`：GitHub trending 仓库每日快照（stars/forks/issues/pushed_at），保留 90 天。给 verdict 判定的"7 天 star 净增"主路径喂数据。
- `data/github_radar.jsonl`：GitHub trending 7 天滚动雷达存档，保留 14 天。**调 verdict 阈值后建议删掉重建**，否则旧标签会污染前端。
- verdict 阈值集中定义在 `github_verdict.py` 顶部，每条都有依据来源。改阈值前先看注释。

## Web 前端样式

`web/` 下的 index.html / style.css / app.js 遵循 **Wired 印刷新闻日报设计语言**（黑白 + 一抹蓝、衬体大字、mono kicker、hairline rule、零 box-shadow、零圆角）。改样式之前先读：

- `web/_design/wired-DESIGN.md` —— 完整 Wired 设计规范（原文，6000+ 字）
- `web/_design/STYLE_DECISIONS.md` —— 项目特异决策（字体替代、verdict 4 档配色方案 B、emoji 全砍策略、信息架构选型、首页结构映射）

**绝不要在不读 STYLE_DECISIONS.md 的情况下改前端**——常见破坏：把 emoji 加回来、给卡片加 box-shadow/border-radius、把 verdict 配色改回饱和色块、引入 Inter/Roboto 等 generic 字体。

样式 token 集中在 `web/style.css` 顶部 `:root { ... }`。改色 / 字体 / 间距请改 token，不要散落写 hex/px。

**v2 前端关键变动**：
- ribbon-tab 从"6 源切换（DIGEST / GitHub / X / HN / Reddit / PH / 量子位）"改为"4 板块切换（MORNING / DISCUSSION / GH RADAR / WEEKEND）"
- 删除"综合精选"区域和 PRIORITY 筛选条
- 卡片新增 `editor_note` 渲染：`<aside class="story-editor-note">` + 左侧 2px `var(--link-blue)` 细线 + 衬体斜体 + caption-gray + "编者按 —" mono 前缀
- 数据读取从 `data.items` / `data.by_source` 改为 `data.by_section`

重构前的原版在 `web/_backup_pre_wired/`，需要对比时去看。
