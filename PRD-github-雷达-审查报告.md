# PRD-github-雷达.md 审查报告

> 审查日期：2026-05-05
> 审查范围：`PRD-github-雷达.md`（V2）对照实际项目代码 + `data/daily/*.json` 历史数据
> 验证基线：6 天日报数据（2026-04-28 ~ 05-05），共 62 条 GitHub items

---

## 审查结论概览

| 严重度 | 数量 | 是否阻塞实施 |
|---|---|---|
| 🔴 致命（功能正确性） | 2 | 是，建议先与产品方对齐 |
| 🟡 数据/预期不准 | 3 | 否，但实施者会被误导 |
| 🟢 文档/维护性瑕疵 | 3 | 否 |

最值得在动手前先和产品方确认的是：**release item 怎么处理** 和 **冷启动期 A 路径的时间窗校验**。其他都是文档/估算精度问题，不阻塞实施。

---

## 🔴 致命问题 1：release 通知在 V2 前端将完全消失

### 现象

`by_source.GitHub` 中实际混有 release item，已通过历史数据确认：

```
2026-05-03.json: gh_rel_314629247 [发布] openai/openai-python v2.33.0
2026-05-04.json: gh_rel_314629247 [发布] openai/openai-python v2.33.0
```

### 矛盾点

PRD §F7.4 要 `annotate()` 跳过 `gh_rel_*`，**不写 `verdict_tag`**：

```python
if (item.get("id") or "").startswith("gh_rel_"):
    continue   # release 没有 stars/forks/issues，不参与 verdict 判定
```

但 PRD §F8.4 又写：

```js
const items = (currentData.by_source?.GitHub || []).filter(it => it.verdict_tag === currentVerdict);
```

→ release item 没有 `verdict_tag`，**4 个子 tab 都会过滤掉它，前端再也看不到 release 通知**。

### 影响

V1 时进入"GitHub 趋势"能看到 release（如 openai-python 新版本发布）；V2 上线后这部分内容彻底消失，属于产品功能丢失。

### 建议修复

PRD 全文未说明此情况。需在动手前与产品方确认：

- 方案 A：单独加一个子 tab "📦 Release"
- 方案 B：把 release 当作"特殊状态"附在某个子 tab 顶部
- 方案 C：明示"V2 期间不展示 release"并写入 PRD §2 非目标

---

## 🔴 致命问题 2：冷启动期 A 路径会用错时间窗口

### 现象

PRD §F6.3 让 `load_recent_snapshots()` 返回带 `age_days` 字段：

```python
{"openai/whisper": {
    "stars": 50000,
    ...
    "snapshot_date": "2026-04-28",
    "age_days": 7
}}
```

但 PRD §F7.2 的判定伪代码完全没用 `age_days`：

```
delta_7d = stars - history[full_name]["stars"]
delta_7d >= 3000 且 open_issues / max(delta_7d, 1) < 0.05
```

### 问题

如果系统只跑了 3 天，history 里只有 3 天前的快照，这段代码会把 `delta_3d` 当成 `delta_7d` 用相同阈值 `_MARKETING_STAR_DELTA_7D = 3000` 比较——**前 7 天里一旦查到 history（无论 age_days 是 1 还是 6），就走 A 路径但阈值是按 7 天校准的**。

结果：冷启动 4-7 天 A 命中率被压得很低，反而比 B 路径更不准；而且越接近第 7 天命中率越接近预期，越早期越偏差，呈现"统计游走"。

### 建议修复

按"窗口完整度"维度补一个判断，二选一：

- **方案 A**：`age_days < 7` 强制退回路径 B（最简单，与 PRD"按仓库粒度自动选"的思路一致）
- **方案 B**：阈值按比例缩放，如 `delta_observed >= 3000 * age_days / 7`

PRD 当前的"按仓库粒度自动切"只考虑了"history 有/无"二元，忽略了"窗口是否满 7 天"这一维度。

---

## 🟡 数据不准 1：§3.1 样本数量

- PRD §3.1 自述："跑了 6 天日报（2026-04-28 ~ 2026-05-05），共 60 条 GitHub items"
- 实际验证：6 天 `by_source.GitHub` 总数 = **62 条**

差异不大但说明 PRD 是大致估算未严格统计，使用其衍生分位数（p75/p90/p95）时实施者应保留 ±5% 容忍度。

---

## 🟡 数据不准 2：hype_only 预期命中数偏离真实分布

### 矛盾

§F7.5 期望："hype_only 应有 1-3 条命中（V1 是 0）"

但根据 §3.1 自己给出的 stars/forks 分布：
- 中位数 11，p75=16，p90=638

将阈值改成 `ratio > 30` 后：
- 大致 10~25% 项目会命中（落在 p75~p90 区间）
- 60 条样本预计命中 **10~15 条**，远高于"1-3 条"

并且 stars > 1000 这个绝对阈值（样本中位数 23k）几乎不构成限制。

### 风险

PRD 用"1-3 条"做自检参考，实施者跑出 12 条命中可能误以为"阈值偏松要回调"，但实际是 PRD 预期数本身估错了。

### 建议

修正 §F7.5 软验收预期为"hype_only 命中 5-15 条之间属正常"，或在阈值常量旁边补一句"按 §3.1 分布预期 hype_only 命中率 ~20%"。

---

## 🟡 数据不准 3：§F7.4 关键陷阱反例数据本身错了

### 现象

PRD §F7.4 反例：

```python
# 如 id="gh_microsoft_TypeScript" 会被解析成 "microsoft/TypeScript"——这次刚好对
# 但 id="gh_huggingface_transformers_js" 会被解析成 "huggingface/transformers_js"
# ——错的，应该是 "huggingface/transformers.js" 之类
```

### 实际情况

实际 [github_collector.py:145](src/collectors/github_collector.py#L145) 用的是：

```python
"id": f"gh_{r['full_name'].replace('/', '_')}"
```

**只 replace 了 `/`，不会动 `.`**。所以 `huggingface/transformers.js` 的真实 id 是：

```
gh_huggingface_transformers.js   （保留了点号）
```

而不是 PRD 写的 `gh_huggingface_transformers_js`。PRD 编造了一个不存在的 id 形式当反例。

### 结论是否仍成立

**是的**——"应当从 url 提 full_name"的核心结论仍正确，因为 owner 名含下划线时（如 `some_user/repo`，id = `gh_some_user_repo`）按 `_` split 仍然不知道在哪切。

但举例数据不准会让实施者疑惑，建议改成 owner 名含 `_` 的真实例子。

---

## 🟢 文档/维护性瑕疵 1：pitfall 命名沿用

§F8.3 让 `pitfallCriteria` 这个 ID 和 CSS 类继续保留。目的是少改 CSS，但板块语义已从"避坑"变"GitHub 雷达"。命名留作技术债，长期维护时会困惑。

**建议**：至少在改造代码时留一行注释，例如：

```html
<!-- 注：ID 名 pitfallCriteria 沿用自 V1，避免追改 web/style.css。语义已变为"GitHub 雷达·当前选中 verdict 的判据卡" -->
```

---

## 🟢 文档/维护性瑕疵 2：丢失 importance 分层未明示

§F8.4 子 tab 内"按 heat_score 排序"，丢失了原 `by_source.GitHub` 的"重磅 → 值得关注 → 了解即可"分层。

V1 已经确定 GitHub 源不展示 importance 标签（见 V1 §0.5），所以这一改动技术上一致，不算 bug。但 PRD 没有显式解释，实施者可能不确定要不要保留 importance 排序。

**建议**：在 §F8.4 加一句"GitHub 源不再用 importance 分层（V1 已决定），子 tab 内只按 heat_score 降序"。

---

## 🟢 文档/维护性瑕疵 3：GitHub Actions 改动表述

§F6.5 写："在 `git add web/data/` 之后追加一行"。

实际 [.github/workflows/daily-digest.yml:53-55](.github/workflows/daily-digest.yml#L53):

```yaml
git add data/daily/
git add web/data/
git diff --cached --quiet || (git commit -m "..." && git push)
```

§0.5 说的"不拆开 commit"自动满足（同一 step 同一 commit）。表述无错误，但可以更精确："在 `git add web/data/` 之后、`git diff --cached --quiet` 之前"——避免实施者把它误加到 commit 之后。

---

## 已验证正确的部分（无需修改）

以下点 PRD 与代码/数据完全一致，已验证：

- §3.2 `donnemartin/system-design-primer` 4-28 stars=372 / 4-29 stars=346035 ✅ 属实
- §3.1 verdict 命中分布 true_use 32% / None 68% ✅ 实测 20/42
- §F7.3 阈值常量备注的 V1 旧值（marketing_phrase_hits=3 / hype_min_stars=500 / hype_star_fork_ratio=100）✅ 与 V1 代码一致
- §F6.4 main.py 改动位置（`enrich_items` 之后、`annotate_github_verdict` 之前）✅ 与 main.py:90-93 对应
- §F8.4 SOURCE_META 中删除 pitfall 条目 ✅ 现有 app.js:7-16 中确实有 pitfall 条目
- §F8.3 删除 `<section id="pitfallSection">` ✅ index.html:116-123 中存在
- collector 字段（`open_issues_count` / `pushed_at` / `created_at`）✅ github_collector.py:94-95 已抓

---

## 建议的实施前 Checklist

动手实施前请先回答：

- [ ] release item 在 V2 中如何展示？（致命问题 1）
- [ ] 冷启动期 4-7 天，路径 A 是否需要按 age_days 校验？（致命问题 2）
- [ ] hype_only 跑出 10+ 条是否符合预期？（数据不准 2，影响自检判断）
- [ ] 是否同意保留 `pitfall*` 命名作为技术债？（文档瑕疵 1）

确认后再按 PRD §0.3 推荐顺序 F6 → F7 → F8 实施。
