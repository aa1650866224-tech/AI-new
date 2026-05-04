# PRD：GitHub 避坑模块（V1）

> 创建日期：2026-05-04
> 范围：仅 GitHub 来源；V2 计划见末尾
> 目标读者：实施这份 PRD 的 Claude Code 会话（冷启动，无前置上下文）

---

## 0. 实施前必读（冷启动指南）

### 0.1 项目速览

这是一个 Python 项目，每日采集多源 AI 资讯生成中文日报。核心管道在 `src/main.py`，**完全是线性的串行管道**：

```
6 个 collector → URL 去重 → 热度评分 → 抓正文 → 翻译 → 分源 top10 → AI 摘要 → 综合精选 → 写 JSON → 同步到 web/
```

前端是 `web/` 下的纯静态 HTML/CSS/JS，读 `web/data/*.json` 渲染。GitHub Actions 每日 UTC 01:00 自动跑全流程并发布到 GitHub Pages。

### 0.2 必读文档（开工前先 Read）

| 文件 | 你要从里面拿什么 |
|---|---|
| `CLAUDE.md` | 整体架构、数据契约、设计陷阱（**特别注意**：`settings.yaml` 中的 `${VAR}` 不会被自动展开，每个模块自己 `os.getenv`） |
| `src/main.py` | 管道串行调用顺序——你的新代码要插在**正确的位置**（具体见 1.5 节） |
| `src/processors/summarize.py` | F1 要重写其中的 `summarize_github_repo()` |
| `src/collectors/github_collector.py` | F2 要在这里加字段抓取 |
| `src/processors/article_fetcher.py` | 了解 GitHub README 是怎么经 `_readme_hint` 临时字段传到 summarize 的 |
| `web/index.html` / `app.js` / `style.css` | F3 / F4 / F5 的前端改动入口 |

### 0.3 环境准备

```bash
pip install -r requirements.txt
# .env 必须有 DEEPSEEK_API_KEY（缺了 summarize 和 translate 都会崩）
# 强烈建议有 GH_PAT（缺了 GitHub API 限额很容易撞上，F2 新增字段会让调用变多）
```

跑本地完整流程：`python src/main.py`
跑前端预览：`cd web && python -m http.server 8080`

### 0.4 推荐实施顺序（有依赖关系，按这个顺序做）

```
Step 1: F2（数据采集 + verdict 判定）  ← 必须先做
   ↓
Step 2: F1（prompt 重写，会用到 verdict_tag）
   ↓
Step 3: F5（去情绪化文案，在 F1 prompt 里顺手做完）
   ↓
Step 4: F3（前端术语词典，独立模块，可与 1-3 并行）
   ↓
Step 5: F4（前端避坑模块，依赖 F1+F2 的输出字段）
```

每完成一步用 `python src/main.py` 跑一次，确认 `data/daily/YYYY-MM-DD.json` 里 GitHub 来源的 item 出现了预期字段，再做下一步。

### 0.5 关键决策的「为什么」——别擅自改回去

以下几个设计是和产品方讨论后**有意为之**，看上去可能反直觉。如果你有更好的想法请先和用户确认，不要直接改：

- **`similar_projects` 允许返回空数组**：AI 圈很多新方向没有真正成熟竞品，强行让 LLM 找会编造。Prompt 里要明确允许"没有合适的就空"。
- **保留英文术语 star / fork / issue 不翻译**：让懂的人不别扭、不懂的人靠 ⓘ 入口学习。**不要改成"收藏数 / 改造数"**。
- **只动 GitHub 一个来源**：营销焦虑主要集中在 GitHub，做透一个再扩展到其他源。其他 5 个源（X / HN / Reddit / 量子位 / ProductHunt）的字段结构和文案**一律不动**。
- **删除 GitHub 源的 `importance` 字段**（重磅 / 值得关注 / 了解即可）：这正是要去除的"焦虑文案"，`verdict_tag` 是它的替代品。但**其他 5 个源照旧返回 `importance`**，前端做条件渲染。
- **历史回访 / 项目坟场放 V2**：工程量大（要新增 tracking 表、周期任务），V1 先把摘要 + 标签 + 词典做扎实。

### 0.6 哪些字段可以放心删 / 改

GitHub 源在本次改造前的输出字段是 `repo_card: {purpose, audience, features[]}`——这是要**整体删掉**的旧设计，不要保留兼容。前端也没有别的页面在读它（只有详情卡渲染用到），改造完一起替换。

---

## 1. 背景与问题

当前 AI 新闻日报会从 GitHub Trending / Releases 抓取项目并展示给读者。但 GitHub 是"营销焦虑"的重灾区：

- 营销号集中放大「3 天狂揽 5000 star」这类话术，制造"不跟上就被淘汰"的恐惧
- 用户实际下载后常发现项目还停留在 Demo 阶段、功能不完善、或者完全不匹配自己需求
- 普通用户看不懂 stars / forks / issues 这些数字背后到底意味着什么，只能被大数字震慑

**目标用户画像**：对 AI 感兴趣、能看懂中文新闻、但不熟悉 GitHub / 不会写代码的"边缘技术圈"读者。他们既不想错过真东西，又怕被忽悠。

**核心定位**：和其他 AI 资讯站正相反——别人帮你发现"今日爆款"，我们帮你判断"这个爆款值不值得你 care"。

---

## 2. 不做什么（非目标）

明确划掉以下范围，避免无限扩张：

- ❌ 不动 X / Hacker News / Reddit / 量子位 / Product Hunt 五个来源（这一期只做 GitHub）
- ❌ 不做用户系统 / 评论 / 收藏 / 个性化
- ❌ 不做邮件 / 飞书 / 微信推送
- ❌ 不做历史追踪 / 项目坟场（放 V2）
- ❌ 不做"作者背景档案"和"issue 区真实声音"（放 V2）
- ❌ 不取代现有「综合精选」和分源选项卡，只在它们旁边新增

---

## 3. V1 功能清单

| 编号 | 功能 | 涉及层 | 依赖 | 推荐顺序 |
|---|---|---|---|---|
| F2 | 大白话项目标签（4 选 1） | 数据采集 + 判定逻辑 | 无 | 1 |
| F1 | 批判式 GitHub 摘要（4 段输出） | LLM prompt | F2 的 verdict_tag | 2 |
| F5 | 去情绪化文案 | prompt + 前端文案映射 | 在 F1 prompt 里顺手做 | 3 |
| F3 | GitHub 术语小词典（5 个术语） | 前端 | 无（可与 1-3 并行） | 4 |
| F4 | 「GitHub 避坑」首页新模块 | 前端 | F1+F2 字段已落地 | 5 |

下面逐项详述。

---

### F1 · 批判式 GitHub 摘要

**现状**：`src/processors/summarize.py::summarize_github_repo()` 输出"项目卖点卡"（`repo_card.purpose / audience / features`），偏向"卖货式"介绍。

**改造**：替换为**祛魅式**四段输出，新字段名建议：

```json
{
  "chinese_title": "用一句话说清这是什么（≤30 字）",
  "verdict": {
    "category_tag": "真新方向 | 老问题的新工具 | 换皮再卷一遍 | Demo 级想法",
    "who_should_care": "分人群说话：'如果你是 X 用户，建议 Y；如果你是 Z 开发者，可以 W'（≤80 字）",
    "prerequisites": "用之前要满足什么：是否需要 GPU / API key / 特定系统 / 英文文档能力 / 编程基础（≤60 字，没有就写'无特殊要求'）",
    "similar_projects": ["项目1", "项目2"]
  },
  "original_excerpt": "从 README 摘 1-2 句最能体现项目定位的英文原文（保留原文）",
  "category": "从原有 6 选 1 类目里选",
  "sentiment": "positive / neutral / negative"
}
```

**关键设计决定**：

- `similar_projects` **可空**。AI 圈很多新方向没有真正成熟竞品，强行让 LLM 找会编造。Prompt 里明确写"如果没有合适的成熟竞品，返回空数组"。
- 删除原来的 `repo_card` 结构，整体替换。
- 删除原来的 `importance` 字段在 GitHub 源的输出（重磅 / 值得关注 / 了解即可）——这正是要去除的"焦虑文案"，由下面 F2 的标签替代。

**Prompt 草稿**（待 PR 实施时进 `summarize.py`）：

```
你是一位有批判精神的开源项目编辑。下面是一个 GitHub 仓库的元信息和 README 片段。
你的任务不是替项目做营销，而是帮中文读者冷静判断"这个项目值不值得我现在 care"。

请严格按 JSON 格式返回，不要包含任何其他文字：
{
  "chinese_title": "...",
  "verdict": {
    "category_tag": "四选一：真新方向 / 老问题的新工具 / 换皮再卷一遍 / Demo 级想法",
    "who_should_care": "分人群说话，明确告诉读者'如果你只是 X，没必要折腾'。≤80 字",
    "prerequisites": "用之前需要满足什么。≤60 字，无特殊要求就直接写'无特殊要求'",
    "similar_projects": ["列出 1-2 个成熟竞品；如没有合适的就返回空数组 []，不要编造"]
  },
  "original_excerpt": "...",
  "category": "...",
  "sentiment": "..."
}

判断 category_tag 的参考：
- 真新方向：解决了过去无成熟方案的问题，或在某个能力上有质的突破
- 老问题的新工具：问题不新，已有 langchain / Cursor / ComfyUI 等成熟方案，本项目是新尝试
- 换皮再卷一遍：本质是已有项目的微调 / fork / 套壳，没有实质增量
- Demo 级想法：仓库还很早期，README 主要是 demo 截图，没有可靠的稳定版

仓库标题：{title}
仓库描述：{description}
README 片段：{readme_hint}
```

---

### F2 · 大白话项目标签

**目的**：在卡片上一眼能看出"这个项目是真热还是炒作"，**不出现任何比例 / 分数 / 增速这种术语**。

**4 个标签**：

| tag id | 中文标签 | 一句解释 | 生活类比 |
|---|---|---|---|
| `true_use` | 🟢 开发者真在用 | 有人提 bug、有人改代码、有人 fork 自己改 | 像本地人天天去的小馆子 |
| `hype_only` | 🟡 看的人多用的人少 | 星很多，但提 issue / fork 的人少 | 像网红店打卡照很多，回头客没几个 |
| `marketing` | 🔴 营销味重 | 星数短期暴涨 + README 充斥"革命性""超越 GPT-4"等 | 像短视频里"3 天瘦 10 斤"那种话术 |
| `abandoned` | ⚫ 已停摆 | 几个月没人维护了 | 像招牌还挂着但已经关门的店 |

**判定逻辑**（写在新模块 `src/processors/github_verdict.py` 中）：

判定需要的字段，必须由 `src/collectors/github_collector.py` 一并抓回来（GitHub API 都能拿到）：

- `stars`（已有）
- `forks`（已有）
- `open_issues_count`（新增）
- `pushed_at` 或 `last_commit_at`（新增）
- `created_at`（新增，用于算 stars/天）
- `recent_stars_7d`（**可选**，需要额外调用，先不强求；没有就用 `stars / age_days` 近似）
- `readme_text` （F1 抓 README 时已经拿到）

判定优先级（**从上往下匹配，命中即停**）：

1. **`abandoned`**：`pushed_at` 距今 > 90 天 → 直接判已停摆
2. **`marketing`**：满足以下任一条件
   - `recent_stars_7d / max(open_issues_count, 1) > 200` （星暴涨但几乎没人提问题）
   - README 中"营销词密度"高：扫描固定词表 `["revolutionary", "state-of-the-art", "best-in-class", "all you need", "超越", "颠覆", "碾压", "完爆"]`，命中 ≥ 3 个不同词
3. **`hype_only`**：`stars / max(forks, 1) > 100` 且 `stars > 500`（星不少但 fork 比例异常低）
4. **`true_use`**：默认兜底（commit 近期 + 有 issue 互动 + fork 比例正常）

**所有阈值都标 `# TODO 调优` 注释**，跑两周后根据实际数据校准。

**输出字段**写入 item：

```json
{
  "verdict_tag": "true_use",
  "verdict_label": "🟢 开发者真在用",
  "verdict_explain": "有人提 bug、有人改代码、有人 fork 自己改",
  "verdict_analogy": "像本地人天天去的小馆子"
}
```

**判定流程位置**：在 `main.py` 的 enrich_items 之后、summarize 之前（这样 LLM 也能看到 verdict_tag，必要时配合调整摘要措辞）。

---

### F3 · GitHub 术语小词典

**核心原则**：保留英文术语（star / fork / issue / commit / release），不翻译，**让懂的人不别扭，让不懂的人有上手坡道**。

**呈现方式**：

- **行内 ⓘ 图标**：术语在卡片 / 详情页第一次出现时，旁边带一个浅灰 ⓘ 图标。鼠标悬停（PC）或点击（移动端）弹出小气泡。
- **底部常驻折叠区**：详情页和首页底部都有一块「📖 看不懂这些数字？」折叠区，展开后是 5 个术语的图文小词典。

**5 个术语文案**（直接进前端 i18n / 常量文件）：

```js
const GITHUB_GLOSSARY = {
  star: {
    name: "Star",
    icon: "⭐",
    desc: "用户点一下表示「我注意到了这个项目」",
    analogy: "类比：朋友圈给一家店点赞，不代表真去吃过",
    meaning: "所以星多 ≠ 好用，只能说明被看见"
  },
  fork: {
    name: "Fork",
    icon: "🍴",
    desc: "别人把项目复制一份到自己账号下，准备自己改它",
    analogy: "类比：把别人的菜谱抄回家改成自己的版本",
    meaning: "fork 数高 = 真有人在用它做事，比 star 更硬的指标"
  },
  issue: {
    name: "Issue",
    icon: "💬",
    desc: "用户报 bug、提建议、问怎么用",
    analogy: "类比：餐厅的顾客留言本",
    meaning: "有人提问 + 作者积极回复 = 项目在认真维护；问题堆着没人回 = 警报"
  },
  commit: {
    name: "Commit",
    icon: "🔨",
    desc: "作者每改一次代码就记录一次",
    analogy: "类比：厨师改菜单",
    meaning: "最近还在 commit = 项目还活着；几个月没动 = 可能弃坑"
  },
  release: {
    name: "Release",
    icon: "📦",
    desc: "作者打包好的「可以用」的版本，比正在开发中的代码可靠",
    analogy: "类比：餐厅正式推出的新菜单 vs 后厨还在试做的实验菜",
    meaning: "没发布过 release 的项目 = 还在 demo 阶段，慎用"
  }
};
```

---

### F4 · 「GitHub 避坑」首页新模块

**位置**：插在「📋 综合精选」和现有分源选项卡之间，作为独立 section。

**模块标题**：`⚠️ GitHub 避坑`
**副标题**：`今日 GitHub 上的爆款，先看清楚再决定要不要折腾`

**展示逻辑**：

- 数据源：今日 GitHub 来源的所有 items
- 排序优先级：`marketing` > `hype_only` > `abandoned` > `true_use`（**红色和黄色排前面**，这是核心反焦虑动作）
- 默认展示前 6 条，下方"展开全部"
- 不再显示原 GitHub 选项卡里那种偏中性的列表（**保留**原选项卡作为"看完整版"入口，只是首页突出"避坑"视角）

**卡片样式**（每张卡片）：

```
┌────────────────────────────────────────────┐
│ 🔴 营销味重                                  │
│ langchain-killer-ultimate ⓘ stars: 5.2K ⓘ  │
│ ───────────────────────────────────────    │
│ 中文标题：又一个号称替代 langchain 的框架      │
│                                             │
│ 该不该 care:                                │
│ 如果你只是想跑个 RAG demo，没必要折腾，等3个月│
│ 看是不是还活着；如果你在做框架研究，可以扫一眼│
│                                             │
│ [查看完整祛魅分析 →]                         │
└────────────────────────────────────────────┘
```

**卡片必须包含**：
1. 顶部彩色标签（F2 的 verdict_label）
2. 项目名 + stars 数（带 ⓘ）
3. 中文标题
4. F1 摘要里的 `who_should_care` 字段（**这是最反焦虑的那一段**）
5. 「查看完整祛魅分析」按钮 → 进详情页

**详情页**显示完整 4 段 verdict + 类比标签 + 底部术语词典。

---

### F5 · 去情绪化文案

**全站 GitHub 部分干掉以下词**：

| 旧词 | 替换 | 出现位置 |
|---|---|---|
| 重磅 | （删除）改用 verdict_label | 前端 importance 标签 |
| 值得关注 | （删除）改用 verdict_label | 前端 importance 标签 |
| 了解即可 | （删除）改用 verdict_label | 前端 importance 标签 |
| 爆火 / 狂揽 / 横扫 | "新增" / "新出现" | 摘要 / 总览文案 |

**实现方式**：
- F1 prompt 里 GitHub 源不再返回 `importance` 字段（其他源照旧返回，不影响）
- 前端在渲染 GitHub 卡片时，若 source == "GitHub" 则隐藏 importance 标签，显示 verdict_label
- `daily_overview()` 的 prompt 加一条："涉及 GitHub 项目时不要用爆火 / 狂揽等词，用'新出现'即可"

---

## 4. 数据契约变更总结

**新增字段**（写入 `data/daily/YYYY-MM-DD.json` 中 GitHub 来源的 item）：

```json
{
  "verdict_tag": "marketing",
  "verdict_label": "🔴 营销味重",
  "verdict_explain": "...",
  "verdict_analogy": "...",
  "verdict": {
    "category_tag": "...",
    "who_should_care": "...",
    "prerequisites": "...",
    "similar_projects": []
  },
  "github_meta": {
    "open_issues_count": 12,
    "pushed_at": "2026-05-01T...",
    "created_at": "2026-04-15T...",
    "recent_stars_7d": 4200
  }
}
```

**删除字段**（仅 GitHub 来源）：
- `importance`（被 verdict_tag 替代）
- `repo_card`（被 verdict 替代）

**保持不变**：
- 所有其他来源（X / HN / Reddit / 量子位 / ProductHunt）的字段结构完全不变
- 顶层 JSON 结构不变（date / generated_at / overview / count / items / by_source）

---

## 5. 实施落点（给后续开发参考）

| 文件 | 改动 |
|---|---|
| `src/collectors/github_collector.py` | 抓取 `open_issues_count` / `pushed_at` / `created_at`，可选 `recent_stars_7d` |
| `src/processors/github_verdict.py` | **新增**，实现 F2 的 4 标签判定逻辑 |
| `src/processors/summarize.py` | 重写 `summarize_github_repo()`，替换 prompt 和返回结构 |
| `src/main.py` | 在 enrich_items 之后、summarize 之前，对 GitHub items 跑 verdict 判定 |
| `web/index.html` | 新增「GitHub 避坑」section + 底部「术语词典」折叠区 |
| `web/app.js` | 新增 verdict_label 渲染、GITHUB_GLOSSARY 常量、ⓘ 气泡组件、避坑模块排序逻辑 |
| `web/style.css` | 4 种 verdict 标签的颜色 + 卡片样式 |

---

## 6. 验收标准

V1 上线后，必须满足以下全部条件才算完成：

- [ ] 当日 GitHub 项目卡片上 100% 显示 4 个 verdict 标签之一
- [ ] 详情页显示完整的 4 段批判式摘要（category_tag / who_should_care / prerequisites / similar_projects）
- [ ] 首页「GitHub 避坑」模块红黄标签项目排在前面
- [ ] 5 个核心术语在卡片中第一次出现时旁边有 ⓘ 入口
- [ ] 详情页和首页底部都有可折叠的「术语小词典」
- [ ] GitHub 卡片不出现「重磅 / 值得关注 / 了解即可」字样
- [ ] `daily_overview` 文案中不出现「爆火 / 狂揽 / 横扫」等词
- [ ] 其他 5 个来源的展示和数据结构完全不受影响

### 6.1 本地验证步骤（实施过程中边做边验证）

每完成一个 F 步骤后按以下方式自检：

**完成 F2 后**：
```bash
python src/main.py
# 打开 data/daily/YYYY-MM-DD.json
# 找一个 source 为 "GitHub" 的 item，确认有：
#   verdict_tag / verdict_label / verdict_explain / verdict_analogy
#   github_meta.{open_issues_count, pushed_at, created_at}
# 抽 5-10 条 GitHub item 看 verdict_tag 分布是否合理（不应全部是同一个标签）
```

**完成 F1 后**：
```bash
python src/main.py
# 同一个 GitHub item 应该多了：
#   verdict.{category_tag, who_should_care, prerequisites, similar_projects}
# 应该没有了：importance, repo_card
# 随机抽 X / HN / Reddit 的 item，确认它们的字段结构和 importance 都没变（回归测试）
```

**完成 F3 后**：
```bash
cd web && python -m http.server 8080
# 访问 http://localhost:8080
# 鼠标悬停 GitHub 卡片中的 stars / forks / issues，应弹出 ⓘ 解释
# 滚到底部，能展开「📖 看不懂这些数字？」折叠区，5 个术语都在
```

**完成 F4 后**：
- 首页应能看到「⚠️ GitHub 避坑」section，位于「综合精选」之后、分源选项卡之前
- 红黄标签项目排在前面（marketing > hype_only > abandoned > true_use）
- 卡片必须显示 4 段批判式摘要里的 `who_should_care`
- 点击「查看完整祛魅分析」进详情页能看完整 4 段

**完成 F5 后**：
- 全站 GitHub 部分搜索「重磅 / 值得关注 / 了解即可 / 爆火 / 狂揽 / 横扫」应**零命中**
- `daily_overview` 文案中也不应出现这些词
- X / HN / Reddit 等其他源仍照常使用 `importance`

### 6.2 上线前最终检查

按 6 章节的 8 条验收清单逐条勾选，全部 ✅ 才算 V1 完成。

---

## 7. V2 路线图（不在本期范围）

供决策时参考，确认 V1 边界用：

- **历史回访 + AI 项目坟场**：对历史 verdict 为 marketing / hype_only 的项目，30 / 90 天后重新抓 GitHub API，判断"当时炒作的项目现在怎样了"，做成专题
- **作者背景小档案**：抓 owner 的 followers / 历史项目，判断"大公司在职 / 知名研究者 / 匿名小号"
- **issue 区真实声音**：抓 top 5 高赞 issue 的标题，特别突出"不能用 / 报错"类反馈
- **3 天延迟发布**：所有新爆款不当天进首页，给社区 72 小时祛魅
- **扩展到其他来源**：把祛魅思路应用到 X 的"惊爆消息" / Product Hunt 的"刷票产品"

---

## 8. 风险与未决问题

- **prompt 的"批判性"会不会过头**：让 LLM 唱衰每一个项目反而失真。需要在 prompt 里强调"如果项目确实有突破，就如实说"。上线后跟踪 1-2 周，看 `category_tag` 分布是否合理（不应全是"换皮"或"Demo"）。
- **判定阈值是拍脑袋定的**：F2 的所有数字（200 / 100 / 90 天）都需要跑数据后调优。建议先用建议值上线，每周看 verdict 分布人工抽查。
- **GitHub API 限额**：新增字段会让每个 repo 多调一次 API（pushed_at / created_at 在原 trending 接口里就有，但 recent_stars_7d 需要单独算）。`recent_stars_7d` 标记为可选，如果限额紧张就跳过，用 `stars / age_days` 近似。
- **README 营销词词表**：是硬编码英文 + 中文混合，将来可能漏检（比如新出现的"vibe-coding 神器"）。预留为常量数组，方便加词。
