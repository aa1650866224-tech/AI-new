# AIHOT 式卡片重设计

- **日期**：2026-05-18
- **状态**：设计已确认，待写实施计划
- **设计参考**：[aihot.virxact.com](https://aihot.virxact.com/) 卡片流形态
- **设计交互记录**：本会话经 brainstorming skill 引导完成
- **视觉验证**：`web/_mockup_v3.html`（含 mockup 服务器 `python -m http.server 8090 --directory web`）

---

## 1. 背景与动机

### 1.1 现状问题

项目当前形态是"按日打包的多板块编辑日报"：

- 每日跑一次 `main.py`，产出 `data/daily/YYYY-MM-DD.json`
- 4 板块按来源性质切分：`morning`（厂商）/ `discussion`（社区）/ `github` / `weekend`（HuggingFace）
- 每条新闻有详情页，承载全文翻译（`chinese_content` 字段）
- `editor_note` 编辑按语 80-120 字，前端渲染为衬体斜体 pull-quote
- 同时维护 `importance` 分级（v1 遗留，v2 已砍但 LLM 偶尔会输出，需要清场）

实际使用观察到三个核心痛点：

1. **详情页 + 全文翻译这套基础设施太重**：抓正文、翻译分级（SHALLOW/DEEP/SKIP）、缓存目录、分段重试、token 爆炸防护——投入很大但读者很少真去看详情页全文（多数人只看卡片）
2. **`editor_note` 80-120 字偏长，且渲染在卡片中间打断事实阅读**：写得像短评但被埋在 pull-quote 里，价值密度高的编辑判断被弱化
3. **卡片信息密度低**：摘要 60-80 字 + 标题 + 来源四个字段就完了，缺少能让读者"看完卡片就够"的信号

### 1.2 参考对象：aihot

aihot 是一个 AI 圈卡片流站点，每条卡片由 6 个区域构成（subagent 实测拆解）：

```
┌──────────────────────────────────────────────────┐
│ 来源 / X handle              + 精选 N            │  Zone 1
├──────────────────────────────────────────────────┤
│ 标题（X 源无独立标题）                            │  Zone 2
├──────────────────────────────────────────────────┤
│ 中段事实层（平均 162 字、新闻通稿口吻）          │  Zone 3
│ [X 推文专属：媒体网格（图片/视频）]              │  Zone 3a
├──────────────────────────────────────────────────┤
│ 标签 × 2-4（硬上限 4）                           │  Zone 4
├─────────── hr 物理分隔线 ────────────────────────┤
│ 推荐理由：[编辑判断层、平均 73 字]              │  Zone 5
└──────────────────────────────────────────────────┘

整个卡片只有 2 个跳转点：标题（RSS）或正文整段（X）跳原文。
```

关键设计判断：

- **承认卡片是主战场**：把摘要、推荐理由、标签、媒体全部塞到卡片正面，不依赖详情页
- **不替读者做二手解读**：点击卡片 = 跳原文，编辑层只做"导航 + 短评判断"，不做"全文翻译镜像"
- **中段（事实）vs 底部（判断）严格分工**：中段平均 162 字、新闻通稿口吻，底部平均 73 字、编辑短评、敢负面评价

### 1.3 本次重构的目标定位

- **不做实时流**：保持每日一次跑 `main.py`，不引入调度器、增量游标、cache 等复杂度
- **不做 AI 长文日报**：只做卡片流，砍掉"今日 AI 速览"`overview` 字段
- **保留 4 板块信息架构**：顶部 tab 仍是 `morning` / `discussion` / `github` / `weekend`，只改造卡片本身
- **GitHub 雷达本轮留空**：现有 verdict 体系全部砍除，雷达 tab 留空状态文案，后续等"人工录入周榜"流程定下来再单独设计
- **X 数据接入本轮不做**：X 推文卡片样式和数据契约字段（`media` / `avatar` / `handle`）作为预留设计保留，但本轮没有 X 采集器、不填充这些字段。X 接入是独立工程（涉及 RSSHub 自托管、cookie 维护、`pbs.twimg.com` 国内访问代理），另起 design 文档单独立项。详见第 9 节

---

## 2. 决策汇总

| # | 决策点 | 选择 |
|---|---|---|
| 1 | 产品形态 | 卡片流（不做 AI 长文日报） |
| 2 | 更新频率 | 每日一次（保持现状） |
| 3 | 顶部 tab | 保留 4 板块 |
| 4 | GitHub 雷达 | 本轮留空，verdict 三个模块全砍 |
| 5 | 卡片样式 | aihot 6 区域 |
| 6 | 详情页 / 翻译 | 砍详情页 + 砍 `translator.py` + 保留 `article_fetcher.py` |
| 7 | 摘要提示词 | 改造为直接消化中英混合输入产中文摘要 |
| 8 | `editor_note` | 30-80 字 / 底部 hr / 前缀"推荐理由：" / GitHub 也加 |
| 9 | 精选 N | 归一化 `heat_score` 到 55-95 区间 / 卡片右上展示 |
| 10 | 多源去重 | 不做（同事件多角度保留） |
| 11 | 历史数据 | 归档到 `web/data/_archive_v3/` |
| 12 | X 推文媒体 | 数据契约加 `media` 字段 / 前端按数据驱动渲染（**本轮预留，X 接入未做**） |
| 13 | 字段命名 | `精选N` 直接用中文 key |
| 14 | `tags` 字段 | 大模型自由生成最多 4 个 |
| 15 | 标题字体修复 | 全局加 `font-feature-settings: "lnum"` 修复 oldstyle figures |
| 16 | masthead 标题 | "AI 新闻日报" 改成 "AI-NEWS" |

---

## 3. 信息架构

### 3.1 整体页面结构

```
┌───────────────────────────────────────────────────────────┐
│  utility bar：DAILY · AI DIGEST     [REFRESH]            │
├───────────────────────────────────────────────────────────┤
│  masthead：AI-NEWS（改自 "AI 新闻日报"）                  │
│  DAILY DIGEST · MULTI-SOURCE EDITORIAL FEED              │
│  每日精选全球 AI 热门资讯 · 多源采集 · 编辑精选            │
├───────────────────────────────────────────────────────────┤
│  ribbon tab（保留 4 板块）：                              │
│  [MORNING 今早必读] [DISCUSSION 圈子在吵]                  │
│  [GH RADAR 雷达]   [WEEKEND 周末再看]                     │
├───────────────────────────────────────────────────────────┤
│  当前板块标题 + 计数                                       │
│  category filter 按钮（保留 6 档完整）：                   │
│  [All][模型发布][产品更新][技术论文][行业观点]              │
│  [投资融资][开源工具]                                      │
├───────────────────────────────────────────────────────────┤
│  卡片流（aihot 6 区域，按热度降序）                        │
│  ...                                                     │
├───────────────────────────────────────────────────────────┤
│  page footer                                              │
└───────────────────────────────────────────────────────────┘
```

### 3.2 砍掉的页面元素

- ❌ utility bar 里的日期选择 select（首页只显示最新一份——具体获取方式：读 `web/data/index.json`，里面已按日期 reverse=True 排序，取第一项即可。**不要**直接拼当前日期字符串，跨时区会出错）
- ❌ "TODAY'S BRIEF · 今日 AI 速览" 整段（对应 `overview` 字段）
- ❌ 详情页 `#detailView` 整块
- ❌ GitHub 雷达 4 档 verdict criteria 区块
- ❌ 底部 GitHub 词典折叠（`<details class="glossary-block">`）

### 3.3 GitHub 雷达 tab 暂时形态

切到 `github` tab 时渲染空状态：

```
┌────────────────────────────────────┐
│  GH RADAR · COMING SOON           │
│                                    │
│  本周榜单待录入                     │
│                                    │
│  GitHub 雷达板块改造中。            │
│  新版将基于人工精选周榜，下周回来。  │
└────────────────────────────────────┘
```

---

## 4. 卡片字段映射 + 提示词改造

### 4.1 卡片 6 区域字段映射

| 区域 | 内容 | 对应 item 字段 | 来源 |
|---|---|---|---|
| 1 左 | 来源（RSS 名 / X 头像 + handle） | `source`（X 源额外 `avatar` / `handle`，本轮预留） | 采集器写入 |
| 1 右 | 精选 N | `精选N` | 评分归一化新增 |
| 2 | 标题（X 源不渲染、字段仍生成） | `chinese_title` | 大模型 |
| 3 | 中段事实层 130-170 字 | `chinese_summary` | 大模型（**长度调整**） |
| 3a | X 推文媒体网格 | `media[]` | 采集器写入（**本轮预留**，仅 X 源带） |
| 4 | 标签 × ≤4 | `tags[]` | 大模型（**新字段**） |
| 5 | 推荐理由 30-80 字 | `editor_note` | 大模型（**长度调整**） |

真正新增的字段：`精选N`、`tags`、`media`。

> 涉及 X 数据的字段（`media` / `avatar` / `handle`）**全部本轮预留、不填充**，详见 § 9。后文不再逐处重复提示。

### 4.2 大模型摘要提示词改造

**通用提示词**（[`summarize.py:44`](src/processors/summarize.py:44) 的 `summarize_item`）改成下面这样：

```python
prompt = f"""你是一位专业的AI新闻编辑。请对以下{source}内容做深度分析，按 JSON 返回。

注意：chinese_summary 与 editor_note 是两个独立字段，分工严格：
- chinese_summary：客观事实层，新闻通稿口吻
- editor_note：主观判断层，编辑视角

输出 JSON：
{{
  "chinese_title": "≤30 字中文标题",

  "chinese_summary": "130-170 字的客观摘要，2-3 句话。新闻通稿口吻，
    可以分点列举关键信息（'核心功能包括：A；B；C'）。包含核心事件 + 
    关键数字/产品名/版本号。禁止'值得关注''重磅'等评价性套话。如果原文
    是英文，直接消化产出中文，不要先翻译再压缩。",

  "tags": ["≤4 个","简短关键词","中英文均可","用于卡片下方展示"],

  "category": "从 [模型发布, 产品更新, 技术论文, 行业观点, 投资融资, 
    开源工具] 中选择最贴合的一个",

  "editor_note": "30-80 字的编辑短评，编辑视角。回答'读者为什么应该
    花时间看这条'——判断 / 对比 / 提醒 / 祛魅，敢负面评价。**禁止重复
    chinese_summary 已经讲过的事实**。口语化，不要场面话。",

  "sentiment": "positive / neutral / negative"
}}

原文标题：{title}
原文内容：{content}
"""
```

> ⚠️ 注意：上面是 Python f-string，**JSON 示例的所有 `{` 和 `}` 在源代码里必须写成 `{{` 和 `}}`**（已转义）。直接复制照抄。

四个核心改动：

1. `chinese_summary` 长度从 60-80 字提到 130-170 字，允许分点列举
2. `editor_note` 长度从 80-120 字缩到 30-80 字
3. 显式说明"英文原文直接消化"（前提：`translator.py` 整个砍掉）
4. 新增 `tags` 字段输出

**配套清理**：把现有 [`summarize.py:67-74`](src/processors/summarize.py:67) 的 JSON 解析失败 fallback 字典里的 `"original_excerpt"` 键也删掉——否则 LLM 解析失败时还会从这里写入 `original_excerpt`，污染已经被砍除的字段。

**GitHub 专属提示词** [`summarize.py:79`](src/processors/summarize.py:79) 的 `summarize_github_repo` 本轮不动——GitHub 雷达留空，这个函数暂时不会被调用，等以后重做雷达时再设计。

### 4.3 热度归一化算法

在 [`ranker.py`](src/processors/ranker.py) 末尾加一个模块级函数（不放进 `Ranker` 类，方便后续单独调用）。**函数名用英文**，但写入的字段 key 仍是中文 `精选N`（决策 #13 约定）：

```python
def normalize_score_band(items: list, floor: int = 55, ceiling: int = 95) -> None:
    """把 heat_score 映射到 floor-ceiling 区间，in-place 写入 item['精选N']。
    
    用最大值线性归一化（不是 z 分数）——
    aihot 实测分布在 55-85，我们用 55-95 留点上调空间。
    跨板块全局归一化（不分 morning/discussion 各算各的）。
    """
    if not items:
        return
    max_score = max((it.get('heat_score', 0) or 0) for it in items)
    if max_score <= 0:
        # 所有条目热度都是 0 或负——直接给一个保底分，避免除零和"全员 ceiling"
        for it in items:
            it['精选N'] = floor
        return
    for it in items:
        raw = it.get('heat_score', 0) or 0
        normalized = floor + (ceiling - floor) * (raw / max_score)
        it['精选N'] = round(normalized)
```

**调用时机**：在 `Ranker.rank()` 里、`sorted(...)` 之后、`return` 之前调用。即：

```python
def rank(self, items: list) -> list:
    for item in items:
        item["heat_score"] = self.score(item)
    sorted_items = sorted(items, key=lambda x: x["heat_score"], reverse=True)
    normalize_score_band(sorted_items)
    return sorted_items
```

### 4.4 数据契约：每条新闻 item 字段

```jsonc
{
  // === 不变 ===
  "id": "...",
  "source": "...",
  "url": "...",
  "title": "...",                    // 原标题
  "content": "...",                  // 原文（抓取后的，仅给提示词用，最终被清掉）
  "created_at": "...",
  "heat_score": 1234.56,
  "section": "morning",
  "category": "模型发布",

  // === 改动长度但字段名不变 ===
  "chinese_title": "...",
  "chinese_summary": "...",          // 130-170 字
  "editor_note": "...",              // 30-80 字

  // === 新增 ===
  "tags": ["GPT-5", "API", "长上下文"],   // ≤ 4
  "精选N": 84,                        // 归一化后的分数 55-95

  // === 新增（本轮预留字段，X 接入后才会有数据填充） ===
  "media": [                         // 可选字段，仅 X 源带
    {
      "type": "image",
      "url": "https://...",
      "thumbnail": null
    },
    {
      "type": "video",
      "url": "https://...",
      "thumbnail": "https://..."     // 视频时必需
    }
  ],
  "avatar": "https://...",           // 可选，仅 X 源带
  "handle": "@username",             // 可选，仅 X 源带

  // === 砍掉 ===
  // "chinese_content"               ❌ translator 砍了
  // "importance"                    ❌ v2 时已砍，再清一次
  // "original_excerpt"              ❌ 卡片不展示原文摘抄
  // "_readme_hint"                  ❌ GitHub 专属临时字段
  // "verdict_tag"                   ❌ 雷达留空，全砍
  // "verdict_label"                 ❌
  // "verdict_explain"               ❌
  // "verdict_analogy"               ❌
  // "verdict.{...}"                 ❌
}
```

**采集器原始字段（`likes` / `retweets` / `replies` / `stars` / `forks` / `author` / `author_followers` 等）**保持现状**——不主动清也不主动用**。前端只读上面列出的卡片字段；保留原始字段方便排查、不影响渲染。如果未来发现 JSON 文件过大再考虑白名单输出。

### 4.5 顶层 JSON 结构

```jsonc
// data/daily/YYYY-MM-DD.json
{
  "date": "2026-05-18",
  "generated_at": "2026-05-18T08:00:00",
  // "overview": "..."                ❌ 砍
  "by_section": {
    "morning":    [item, item, ...],
    "discussion": [item, item, ...],
    "github":     [],                 // 留空数组
    "weekend":    [item, ...]
  }
}
```

---

## 5. 数据流改造

### 5.1 新旧流程对照

| 步骤 | 现状 | 新设计 |
|---|---|---|
| 1. 采集器并行 | 5 个（HN/Reddit/RSS/GitHub/HF） | 4 个，砍 GitHub 采集（雷达留空） |
| 2. URL 去重 | 保留 | 保留 |
| 3. 热度评分 | `heat_score` | + 归一化写入 `精选N` |
| 4. 抓正文 | 保留 | 保留（仅给提示词用） |
| 5. GitHub 避坑判定 | 跑 | ❌ 砍 |
| 6. 翻译 | 全文翻译，落盘 `chinese_content` | ❌ `translator.py` 整个删 |
| 7. 板块映射 | 保留 | 保留 |
| 8. 板块切分 + 容量上限 | morning ≤ 8、discussion ≤ 10 | 保留同上限 |
| 9. 大模型摘要 | 通用 / GH 双路径 | 只走通用路径，新提示词 |
| 10. GitHub 雷达 7 天滚动 | 跑 | ❌ 砍 |
| 11. 防御性清场 | 清 `importance` | 扩展：清所有砍掉字段 + `content` |
| 12. 今日 AI 速览 | 跑 | ❌ 砍 |
| 13. 存储 + 同步 `web/data` | 保留 | 结构变化（无 `overview`） |
| 14. GitHub 历史快照 | 跑 | ❌ 砍 |

### 5.2 新流程图

```
              ┌───────────────────────────────┐
              │ 采集（4 个采集器并行）         │
              │   - HN / Reddit / RSS / HF    │
              │   - GitHub 暂停（雷达留空）    │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ URL 去重                       │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 热度评分 + 归一化              │
              │   - heat_score 保留           │
              │   - 新增 `精选N` 写入          │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 抓正文（给提示词用，不落盘）   │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 板块映射 + 切分 + 容量上限     │
              │   - morning ≤ 8               │
              │   - discussion ≤ 10           │
              │   - github 直接置空           │
              │   - weekend 不限              │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 大模型摘要（新提示词）         │
              │   - chinese_title             │
              │   - chinese_summary 130-170字 │
              │   - editor_note 30-80 字      │
              │   - tags ≤ 4                  │
              │   - category                  │
              │   - sentiment                 │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 防御性清场                     │
              │   清掉所有砍除字段：          │
              │   content, chinese_content,   │
              │   importance,                 │
              │   original_excerpt,           │
              │   _readme_hint,               │
              │   _section_hint,              │
              │   _translation_content,       │
              │   verdict_tag/label/explain/  │
              │     analogy,                  │
              │   verdict.*, repo_card,       │
              │   radar_date                  │
              └────────────────┬──────────────┘
                               ▼
              ┌───────────────────────────────┐
              │ 存储 + 同步 web/data           │
              │   data/daily/YYYY-MM-DD.json  │
              │   web/data/YYYY-MM-DD.json    │
              │   web/data/index.json         │
              └───────────────────────────────┘
```

### 5.3 关键设计决策

**决策 A：GitHub 采集 + Verdict + 滚动 全链路清理**

`github_verdict.py` / `github_aggregate.py` / `github_snapshot.py` 三个文件砍除后（详见 § 8.1），[`main.py`](src/main.py) 里依赖它们的调用点会全部 ImportError。下面给出 `main.py` 完整清理清单：

**删除的 import**（约 [`main.py:25-28`](src/main.py:25)）：

```python
# 删：
from src.processors.github_verdict import annotate as annotate_github_verdict
from src.processors import github_snapshot
from src.processors import github_aggregate
```

**改 sources 列表**（约 [`main.py:56-62`](src/main.py:56)）—— 删 GitHub 那行（不要注释，直接删）：

```python
sources = [
    ("Hacker News", HNCollector),
    ("Reddit", RedditCollector),
    ("RSS feeds", RSSCollector),
    ("HuggingFace", HFCollector),
]
```

**删除的代码块**：

- 约 [`main.py:99-100`](src/main.py:99)：`history = github_snapshot.load_recent_snapshots(...)` + `annotate_github_verdict(items, history=history)` —— 两行删
- 约 [`main.py:129-140`](src/main.py:129)：「GitHub 雷达 7 天滚动累积」整段（含 `aggregate_7days` / `append_today` / `prune_old`）—— 整段删
- 约 [`main.py:182-190`](src/main.py:182)：「F6：追加今日 GitHub trending 快照」整段（含 `append_today_snapshot` / `prune_old_snapshots`）—— 整段删
- 约 [`main.py:32-33`](src/main.py:32) 的 `SNAPSHOT_PATH_ABS` / `RADAR_PATH_ABS` 常量定义 —— 删

**保留的逻辑**：`by_section["github"]` 由 `split_by_section()` 创建为空数组（因为没有 source=GitHub 的条目进来），无需手动置空。

**决策 B：`article_fetcher.py` 保留但产出不落盘**

抓回的正文（`item["content"]`）只给大模型摘要提示词用，不写到最终 JSON。具体做法：在防御性清场阶段把 `content` 从 item 里 pop 掉。

这样既保住摘要质量（提示词有充分输入），又不让 JSON 文件被长文撑大。

**决策 C：长度截断逻辑保留 + summarize.process_batch 清理**

`translator.py` 这个文件本身砍掉，但里面的 `SHALLOW_LIMIT = 200` 和 `DEEP_LIMIT = 5000` 常量值得保留——作用于 `content` 字段在送进摘要提示词之前的预处理，控制提示词长度。

**落地位置：搬进 `summarize.py`**（不放 `article_fetcher.py`），因为这是给摘要提示词用的，逻辑归属应该跟着提示词走。`Summarizer.process_batch()` 在调用 `summarize_item()` 前对 `item["content"]` 按 source 类型做截断。

`SHALLOW_SOURCES`（X/HN/Reddit）→ 200 字；其它源 → 5000 字；GitHub/HuggingFace 仍跳过（GitHub 雷达留空，本轮采集器也没跑）。

**配套清理**：[`summarize.py:199`](src/processors/summarize.py:199) 当前是

```python
text = item.get("chinese_content") or item.get("content", "")
```

`translator.py` 砍后 `chinese_content` 永远是 None，这个 fallback 表达式变成死代码。**改成直接读 `content`**：

```python
text = item.get("content", "")
```

对一般文章和短内容无影响；对 30000 字以上的学术综述长文会损失"举例丰富度"，但摘要本来也就 130-170 字，写不进那么多细节。可调参数，发现问题再调高。

**决策 D：`article_fetcher.py` 内部清理**

`article_fetcher.py` 文件保留，但内部 GitHub README 抓取分支整段可以删（既然 GitHub 采集器砍了，永远走不到那段）。保留的逻辑：

- 域名分流 SKIP 列表（reddit / youtube / medium 等不抓正文）
- arxiv 走官方 API 取 abstract
- trafilatura 抓普通文章正文
- 按 URL 哈希缓存到本地

要砍的逻辑：

- GitHub 仓库走 GitHub API 拿 README 的分支
- 写入 `_readme_hint` 临时字段的代码

---

## 6. 前端改造

### 6.1 改动概览

| 文件 | 改动量 | 主要变化 |
|---|---|---|
| `web/index.html` | 中等 | 砍详情页、砍日期选择、砍速览块、masthead 标题改 "AI-NEWS" |
| `web/style.css` | 较大 | 全局加 lining 数字修复、新增 6 区域卡片样式、新增 X 媒体网格样式、砍详情页样式、砍 verdict 专属样式 |
| `web/app.js` | 较大 | 砍详情页路由、砍速览渲染、砍 verdict 4 档 tab、新卡片渲染函数 |
| `web/_design/STYLE_DECISIONS.md` | 小 | 追加 V3 设计决策章节 |

### 6.2 砍掉的前端元素

- ❌ utility bar 日期选择 `<select id="dateSelect">`（REFRESH 按钮保留）
- ❌ `<section class="brief" id="overviewSection">` 今日速览
- ❌ `<section id="pitfallCriteria">` 雷达 4 档 verdict tab
- ❌ `<details class="glossary-block">` GitHub 词典折叠
- ❌ `<div id="detailView">` 详情页整块

### 6.3 新增的前端元素

- ✅ `<section id="newsList" class="v3-card-list">` 卡片流容器（替代旧 `.story-list`）
- ✅ 切到 github tab 时渲染空状态文案（"本周榜单待录入"）

### 6.4 全局字体修复

加在 `style.css` 的 `:root` 同级（修复 Playfair Display 默认 oldstyle figures 导致 "GPT-5" 这种字母+数字组合数字看起来低一截）：

```css
html, body {
    font-feature-settings: "lnum" 1, "tnum" 1;
    font-variant-numeric: lining-nums tabular-nums;
}
```

### 6.5 卡片渲染函数（app.js）

辅助函数 `escapeHtml` / `escapeAttr` 在 `app.js` 顶部定义（项目当前没有，本轮新加）：

```js
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
function escapeAttr(s) { return escapeHtml(s); }
```

板块切换时的总渲染入口：

```js
function renderSection(sectionName, items) {
    const list = document.getElementById('newsList');
    // github 板块本轮留空
    if (sectionName === 'github' || !items || items.length === 0) {
        list.innerHTML = sectionName === 'github'
            ? renderEmptyState()
            : '<p class="page-desc">该板块今日暂无内容。</p>';
        return;
    }
    list.innerHTML = items.map(renderCard).join('');
}

function renderEmptyState() {
    return `
    <section class="v3-empty-state">
        <div class="v3-empty-mono">GH RADAR · COMING SOON</div>
        <div class="v3-empty-title">本周榜单待录入</div>
        <p class="v3-empty-desc">GitHub 雷达板块改造中。<br>新版将基于人工精选周榜，下周回来。</p>
    </section>`;
}
```

单卡片渲染：

```js
function renderCard(item) {
    // X 推文头部：头像 + handle
    // fallback 首字母从 handle 取（@username 去掉 @），而不是 source（中文源名取首字会很丑）
    const fallbackInitial = ((item.handle || '').replace(/^@/, '') || item.source || '?')[0].toUpperCase();
    const xHead = item.handle ? `
        <div class="v3-head-x">
            <div class="v3-avatar">
                ${item.avatar ? `<img src="${escapeAttr(item.avatar)}" alt="">` : fallbackInitial}
            </div>
            <div>
                <span class="v3-source-x">${escapeHtml(item.source)}</span>
                <span class="v3-handle">${escapeHtml(item.handle)}</span>
            </div>
        </div>
    ` : `<span class="v3-source">${escapeHtml(item.source)}</span>`;

    // 媒体网格（数据驱动：任何 item 有 media 字段就渲染）
    let mediaHtml = '';
    if (item.media && item.media.length > 0) {
        const list = item.media.slice(0, 4);
        const cells = list.map(m => {
            const src = m.thumbnail || m.url;
            const cls = m.type === 'video' ? 'v3-media-cell is-video' : 'v3-media-cell';
            return `<div class="${cls}"><img src="${escapeAttr(src)}" alt=""></div>`;
        }).join('');
        mediaHtml = `<div class="v3-media media-${list.length}">${cells}</div>`;
    }

    const tags = (item.tags || [])
        .slice(0, 4)
        .map(t => `<span class="v3-tag">${escapeHtml(t)}</span>`)
        .join('');

    return `
    <article class="v3-card" data-url="${escapeAttr(item.url)}">
        <div class="v3-head">
            ${xHead}
            <span class="v3-score-badge">
                + 精选 <span class="v3-score-num">${item['精选N'] ?? 0}</span>
            </span>
        </div>
        ${item.chinese_title ? `<h2 class="v3-title">${escapeHtml(item.chinese_title)}</h2>` : ''}
        <p class="v3-summary">${escapeHtml(item.chinese_summary)}</p>
        ${mediaHtml}
        <div class="v3-tags">${tags}</div>
        <hr class="v3-divider">
        <div class="v3-reason">
            <span class="v3-reason-label">推荐理由：</span>
            <span class="v3-reason-text">${escapeHtml(item.editor_note || '')}</span>
        </div>
    </article>`;
}

// 卡片整体点击跳原文
document.addEventListener('click', e => {
    const card = e.target.closest('.v3-card');
    if (card && card.dataset.url) {
        window.open(card.dataset.url, '_blank', 'noopener');
    }
});
```

### 6.6 媒体网格布局规则

- 1 张 → 单格大图
- 2 张 → 左右平分
- 3 张 → 左大右两小
- 4 张 → 2x2 网格
- ≥ 5 张 → 截断到 4，多余忽略

### 6.7 历史数据归档 + 运行时产物清理

#### 6.7.1 归档（保留以备查）

`web/data/*.json`（旧版结构日报）—— 在改动前归档。**项目在 Windows 上开发**，下面给两套命令任选：

**PowerShell**：

```powershell
New-Item -ItemType Directory -Force -Path web/data/_archive_v3 | Out-Null
Get-ChildItem web/data/*.json -Exclude index.json | Move-Item -Destination web/data/_archive_v3/

New-Item -ItemType Directory -Force -Path data/_archive_v3 | Out-Null
Get-ChildItem data/daily/*.json -ErrorAction SilentlyContinue | Move-Item -Destination data/_archive_v3/
```

**git-bash / WSL / Linux**：

```bash
mkdir -p web/data/_archive_v3
find web/data -maxdepth 1 -name '*.json' ! -name 'index.json' -exec mv {} web/data/_archive_v3/ \;

mkdir -p data/_archive_v3
mv data/daily/*.json data/_archive_v3/ 2>/dev/null || true
```

`index.json` 不归档，会被下次跑 `main.py` 时重建。旧数据保留在 `_archive_v3/` 目录里以备查，前端不读。

#### 6.7.2 直接删除（运行时产物，无归档价值）

下列产物每次 `main.py` 跑都会重建/积累，归档没意义、留着会被新规则污染：

**PowerShell**：

```powershell
Remove-Item -Force -ErrorAction SilentlyContinue data/github_radar.jsonl
Remove-Item -Force -ErrorAction SilentlyContinue data/github_snapshots.jsonl
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue data/article_cache
```

**git-bash / WSL / Linux**：

```bash
rm -f data/github_radar.jsonl
rm -f data/github_snapshots.jsonl
rm -rf data/article_cache/
```

#### 6.7.3 Mockup 文件命运

`web/_mockup_v3.html` 在重构完成后**删除**——它的所有视觉决策已落进 `web/index.html` + `web/style.css`，留着会造成"两套实现"的维护负担。

---

## 7. 媒体字段的数据契约补充（本轮预留）

> **本轮重构不会有数据填这些字段**——X 采集器是独立立项（详见第 9 节）。这里写下字段定义，让前端渲染逻辑提前预留好，X 接入后无需再改前端。

`media` 字段：

```jsonc
"media": [
  {
    "type": "image" | "video",
    "url": "https://...",            // 原始资源 URL
    "thumbnail": "https://..."       // type=video 时必需；type=image 时可选
  }
]
```

采集层填充策略：

- **X / 推特源**（未来通过 RSSHub 接入）：从 RSSHub feed entry 的 enclosure / `media:content` 标签抽出
- **其他源**（RSS / HN / Reddit / HF）：默认不填 `media`
- 任何源都可以填——前端按数据驱动渲染，不靠 source 名硬判断

---

## 8. 砍除清单（汇总）

### 8.1 模块/文件级砍除

- ❌ `src/processors/translator.py` 整个文件删除
- ❌ `src/processors/github_verdict.py` 整个文件删除
- ❌ `src/processors/github_aggregate.py` 整个文件删除
- ❌ `src/processors/github_snapshot.py` 整个文件删除
- ❌ `data/github_radar.jsonl` 删除（雷达留空，不再累积）
- ❌ `data/github_snapshots.jsonl` 删除（snapshot 模块都砍了）
- ❌ `data/article_cache/` 目录删除（详情页砍了，缓存不需要）

### 8.2 字段级砍除（每条 item）

- ❌ `chinese_content`
- ❌ `importance`
- ❌ `original_excerpt`
- ❌ `_readme_hint`
- ❌ `_section_hint`
- ❌ `_translation_content`
- ❌ `verdict_tag` / `verdict_label` / `verdict_explain` / `verdict_analogy`
- ❌ `verdict.*`
- ❌ `repo_card`
- ❌ `radar_date`

### 8.3 顶层 JSON 字段砍除

- ❌ `overview`
- ❌ `items`（v1 遗留）
- ❌ `by_source`（v1 遗留）
- ❌ `count`（v1 遗留）

### 8.4 前端元素砍除

- ❌ `<select id="dateSelect">`
- ❌ `<section class="brief" id="overviewSection">`
- ❌ `<section id="pitfallCriteria">`
- ❌ `<details class="glossary-block">`
- ❌ `<div id="detailView">`

---

## 9. 未来工作（X 数据接入，独立立项）

X 数据接入**不在本轮 scope 内**，但因为 aihot 卡片设计高度依赖 X 推文呈现，本轮的卡片样式 + 数据契约要为 X 数据预留好接口，避免接入时还要回头改前端。

### 9.1 本轮为 X 接入做的预留

- 数据契约：`media[]` / `avatar` / `handle` 三个字段已经定义
- 前端：`renderCard()` 函数已经包含 X 头部分支（检测 `item.handle` 存在则渲染头像 + handle，否则走 RSS 标准头部）
- CSS：`v3-head-x` / `v3-avatar` / `v3-handle` / `v3-media` / `v3-media-cell` / `v3-media.is-video` 全部已在 `_mockup_v3.html` 验证

X 接入工程上线时无需改前端，只要 X 采集器开始往 item 里填这三个字段就会自动渲染。

### 9.2 X 接入项目大致任务清单（仅供下一立项参考）

1. **本地 Docker 部署 RSSHub**（半天）
   - 拉镜像、配置 X 路由依赖
   - 配置 X cookie / `auth_token` 环境变量（需小号配合）
2. **维护"AI 圈大 V" X handle list**（运营，持续）
   - 初始 30-50 个核心 handle
   - 可参考 aihot 信源墙
3. **写 X 采集器** `src/collectors/x_collector.py`（半天）
   - 拉 RSSHub `/twitter/user/:handle` 或 `/twitter/list/:owner/:list`
   - 解析 RSS entry → 提取 handle / avatar / media URL / 文本 / created_at
   - 写入 item，`source` 字段填用户名
4. **解决 `pbs.twimg.com` 国内访问问题**（1-2 天）
   - 方案 A：Cloudflare Worker 反代 → 在前端 URL 重写时改成自家域名
   - 方案 B：本地起 nginx reverse proxy
   - 方案 C：下载到本地缓存，前端走本地路径
5. **稳定运行环境**
   - 本机 7×24 运行 RSSHub，或迁到 VPS
6. **维护性问题**
   - X cookie 几周一过期，需要小号续期机制
   - X 反爬升级时 RSSHub 路由可能挂，需关注社区更新

预估总工作量：**5-8 天**（不含 ongoing 运维）。

## 10. 附录：参考资料

### 10.1 aihot 卡片实测拆解（subagent 报告摘要）

- **卡片结构**：6 区域，整个卡片只有 2 个跳转点（标题或正文段跳原文）
- **中段文本性质**：客观事实层，双轨制——RSS 长文源是 AI 改写后的新闻通稿口吻，X 推文源是原文翻译（保留 emoji、引用前缀）
- **中段长度**：min 31 / avg **162** / max 302 字
- **底部推荐理由**：min 38 / avg **73** / max 121 字，编辑口吻、敢负面评价
- **精选 N 数字**：min 57 / avg 71 / max 84，class 后缀 `score-mid/low/high` 分段着色，绝对热度分
- **标签**：硬上限 4 个，`tag-static` 不可点击
- **页面 sub-tab**：6 个 category（全部 / 模型 / 产品 / 行业 / 论文 / 技巧），按内容性质切

### 10.2 关键代码文件路径

- 入口：[`src/main.py`](src/main.py)
- 摘要：[`src/processors/summarize.py`](src/processors/summarize.py)
- 评分：[`src/processors/ranker.py`](src/processors/ranker.py)
- 抓正文：[`src/processors/article_fetcher.py`](src/processors/article_fetcher.py)
- 板块映射：[`src/processors/section_mapper.py`](src/processors/section_mapper.py)
- 前端入口：[`web/index.html`](web/index.html)
- 样式：[`web/style.css`](web/style.css)
- 应用逻辑：[`web/app.js`](web/app.js)
- 设计规范：[`web/_design/STYLE_DECISIONS.md`](web/_design/STYLE_DECISIONS.md)

### 10.3 aihot X 数据接入路径调查（subagent 实测）

通过浏览 aihot 子页面（`/about` / `/changelog` / `/submit` / `/agent`）得到的硬证据：

- **changelog 5/7 那条**承认"原本 X 头像 / 媒体走 `pbs.twimg.com` 直链，国内 ISP 全屏蔽……现在走自建图片代理 + 自动 webp 压缩"
- `pbs.twimg.com` 是 X 官方 CDN 域名 → 说明他们拿到的图片 URL 是原始 X URL，**不是 nitter / xcancel 镜像站重写过的 URL**
- **信源提报支持裸 X handle 和单条推文 URL**——符合 RSSHub `/twitter/user/:id` 路由的运营模式
- **未公开任何技术栈细节**

结论：**aihot 最可能走 RSSHub 自托管 + X 官方资源直链 + 自建图片代理**，置信度约 75%。

### 10.4 Mockup 验证

- 文件：`web/_mockup_v3.html`
- 启动：`python -m http.server 8090 --directory web`
- 地址：`http://localhost:8090/_mockup_v3.html`
- 已验证：masthead "AI-NEWS"、`v3-title` lining figures 数字修复、X 卡片头像 / handle / 媒体网格、视频缩略带 ▶️ 角标
