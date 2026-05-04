# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI 新闻日报助手：每日从 X / Hacker News / Reddit / GitHub / Product Hunt / RSS（量子位）多源采集 AI 资讯，经评分、去重、抓取正文、翻译、AI 摘要后，输出 JSON 日报和静态 Web 看板。GitHub Actions 每日 UTC 01:00（北京时间 09:00）自动跑全流程并发布到 GitHub Pages。

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

无测试套件、无 lint 配置；根目录的 `test_ph.py` / `test_ph2.py` 是 ProductHunt 的临时调试脚本，不是单元测试。

## 环境变量

`src/main.py` 启动时通过 `python-dotenv` 自动加载项目根目录的 `.env`；GitHub Actions 通过 Secrets 注入。

| 变量 | 用途 | 来源 |
|---|---|---|
| `DEEPSEEK_API_KEY` | AI 摘要 + 翻译，所有 LLM 调用都走 DeepSeek | 必需 |
| `X_BEARER_TOKEN` | X (Twitter) v2 API | 缺失则跳过 X 源 |
| `GH_PAT` | GitHub API 限流提升（**不要**用 `GITHUB_TOKEN` 前缀，Actions 会保留这个名字） | 可选 |
| `PRODUCTHUNT_TOKEN` | Product Hunt API | 可选 |

`config/settings.yaml` 中的 `${VAR}` 语法**不会**被自动展开——代码在每个 collector / processor 内部单独 `os.getenv(...)`，YAML 里的占位符仅作文档用途。

## 整体流水线（src/main.py）

`main()` 是一条线性管道，理解这个顺序对改任何环节都关键：

1. **采集**：6 个 collector 串行调用，**单个源失败不影响其他源**（每个 collector 套 `try/except`）。collector 优先尝试 `fetch(keywords_config=...)`，不支持则 `TypeError` 回退到 `fetch()`——新增 collector 时两种签名都可以。
2. **URL 去重** (`processors/dedup.py::url_dedup`)：在评分前做，归一化掉 `www.` 和尾部斜杠。
3. **热度评分** (`processors/ranker.py`)：likes / retweets / replies / stars / forks 加权求和，大 V (`author_followers >= follower_threshold`) 加成，超过 `decay_hours` 后线性衰减。所有时间统一转 UTC aware datetime。
4. **正文抓取** (`processors/article_fetcher.py::enrich_items`)：用 `trafilatura` 抓外链正文，按 URL 哈希缓存到本地。**域名分流**：`SKIP_DOMAINS`（x.com / reddit / youtube / medium 等）跳过；arxiv 走官方 API 拿 abstract；GitHub 仓库走 GitHub API 拿 README，结果存到临时字段 `_readme_hint`。
5. **翻译** (`processors/translator.py`)：英文正文长文分段翻译为中文，写入 `chinese_content`。翻译前会把图片 Markdown `![](...)` mask 成占位符，避免 LLM 改坏 URL。
6. **分源 Top 10**：从已排序的 items 里按 `source` 字段切，存进 `by_source`。**source 字符串必须和 `source_names` 里的列表完全一致**（`X` / `HackerNews` / `Reddit` / `GitHub` / `量子位` / `ProductHunt`），否则前端选项卡和后端切片会对不上。
7. **AI 摘要** (`processors/summarize.py`)：合并所有需要摘要的 id 一次性跑，避免重复调 API。**GitHub 源走专属 prompt** `summarize_github_repo()`（基于 `_readme_hint` 输出 `repo_card` 结构），其他源走通用 `summarize_item()`，优先用 `chinese_content` 而非原始 `content`。摘要完成后 `_readme_hint` 会被 pop 掉，不写入最终 JSON。
8. **综合精选**：从 `summarized_map` 里按 `importance` 分层挑选——先填 `重磅`，不够再补 `值得关注`，再补 `了解即可`，每层内按 `heat_score` 排序，最后再做一次 URL 去重，截到 `daily_top_n`（默认 15）。
9. **日报总览**：`summarizer.daily_overview()` 用 LLM 生成 200 字"今日 AI 速览"。
10. **存储**：`storage/json_storage.py` 写 `data/daily/YYYY-MM-DD.json`，再 `copy_to_web()` 同步到 `web/data/`，最后用 glob 重建 `web/data/index.json`（前端用它列出可选日期）。

## 数据契约

LLM 输出的字段是前端和后续处理的硬约束，改 prompt 时必须保留：

- `importance` ∈ {`重磅`, `值得关注`, `了解即可`}——综合精选的分层依据
- `category` ∈ {`模型发布`, `产品更新`, `技术论文`, `行业观点`, `投资融资`, `开源工具`}——前端筛选用
- `chinese_title` / `chinese_summary` / `original_excerpt` / `sentiment`
- GitHub 源额外有 `repo_card: {purpose, audience, features[]}`

每日 JSON 顶层结构：`{date, generated_at, overview, count, items[], by_source{}}`。`items` 是综合精选 top N，`by_source` 是分源 top 10。

`processors/dedup.py::cluster_dedup` 用硬编码关键词列表（openai / gpt / claude / anthropic / gemini / google / llama / meta / deepseek / mistral / microsoft / nvidia）做粗聚类，限制同一类事件最多 `max_per_cluster` 条——但**目前 main.py 没调用它**，只用了 `url_dedup`。如果发现"重复事件刷屏"想启用，记得在评分后插入。

## 配置

- `config/settings.yaml`：API endpoint、各源阈值（`min_likes` / `min_score` / `trending_count` 等）、评分权重、`daily_top_n`。
- `config/keywords.yaml`：`include` 用于过滤抓取内容，`exclude` 用于屏蔽抽奖/加密币/web3 等噪声。会被 `main.py` 注入到 `config["keywords"]` 透传给 collector。

## GitHub Actions

`.github/workflows/daily-digest.yml` 在 cron 触发后会：跑 `python src/main.py` → 重建 `web/data/index.json` → **把 `data/daily/` 和 `web/data/` 提交回仓库** → 把整个 `web/` 作为 artifact 部署到 Pages。所以本地跑出的日报 commit 会和 Action 自己的 commit 共存，`data/daily/` 是单一事实来源。

## 项目状态参考

`AGENTS.md` 和 `NEXT_STEPS.md` 是前任开发者留下的进度笔记（最后更新 2026-04-28）。它们的"待办"已部分过时，但里面的"上次未完结的问题"和 API key 说明仍然有参考价值——改动相关功能前可以看一眼。
