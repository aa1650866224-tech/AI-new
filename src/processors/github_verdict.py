"""
F2 + F7：GitHub 项目"避坑标签"判定器

输入：collector 拿回来的 GitHub item（需要 github_meta + 可选 _readme_hint），
      以及 F6 提供的 7 天历史快照映射（可选）。
输出：在 item 上添加 verdict_tag / verdict_label / verdict_explain / verdict_analogy

判定优先级（从上往下，命中即停）：
  1. abandoned   ：pushed_at 距今 > 90 天
  2. marketing   ：7 天 star 净增大 + 提问题的人少（有 7 天历史时）；
                   或 冷启动 stars_today 近似；或 README 命中 ≥ 4 个营销词
  3. hype_only   ：stars > 1000 且 stars / forks > 30
  4. true_use    ：默认兜底

阈值依据见 PRD §3（基于 62 条真实样本的合理初值）。
"""
from __future__ import annotations

from datetime import datetime, timezone


# ---- 4 个标签的元信息（V1 已落地，前端依赖） ----
VERDICT_META = {
    "true_use": {
        "label": "🟢 开发者真在用",
        "explain": "有人提 bug、有人改代码、有人 fork 自己改",
        "analogy": "像本地人天天去的小馆子",
    },
    "hype_only": {
        "label": "🟡 看的人多用的人少",
        "explain": "星很多，但提 issue / fork 的人少",
        "analogy": "像网红店打卡照很多，回头客没几个",
    },
    "marketing": {
        "label": "🔴 营销味重",
        "explain": "星数短期暴涨 + 提问题的人少",
        "analogy": "像短视频里「3 天瘦 10 斤」那种话术",
    },
    "abandoned": {
        "label": "⚫ 已停摆",
        "explain": "几个月没人维护了",
        "analogy": "像招牌还挂着但已经关门的店",
    },
}

# README 里命中即记一次的"营销词"（中英混合）
_MARKETING_PHRASES = [
    "revolutionary",
    "state-of-the-art",
    "best-in-class",
    "all you need",
    "game-changer",
    "game changer",
    "超越",
    "颠覆",
    "碾压",
    "完爆",
]

# === 阈值集中区 ===
# 所有数字都是基于 62 条真实样本（2026-04-28 ~ 05-05）的合理初值
# TODO 调优：上线 2 周后人工抽 20 条 verdict 命中项目核对，再校准

_ABANDONED_DAYS = 90              # pushed_at 超过 N 天 → abandoned

# marketing 路径 A（主判据，需要 7 天历史）
_MARKETING_STAR_DELTA_7D = 3000   # 7 天 star 净增 ≥ 此值
_MARKETING_ISSUE_RATIO = 0.05     # open_issues / 7天star增量 < 此值

# marketing 路径 B（冷启动，无快照时退化用 stars_today）
_MARKETING_COLD_STARS_TODAY = 1500
_MARKETING_COLD_RATIO = 0.05

# marketing 路径 C（README 营销词兜底，权重降低）
_MARKETING_PHRASE_HITS = 4        # 旧 V1 是 3，本期收紧到 4

# hype_only（按真实分布 p75~p90 校准）
_HYPE_MIN_STARS = 1000            # 旧 V1 是 500
_HYPE_STAR_FORK_RATIO = 20        # 旧 V1 是 100 → V2 是 30 → 现在 20。
                                  # 依据：Awesome Agents/Dagster 文献给出健康项目 stars/forks 在 5~10，
                                  # CMU StarScout 论文 Union Labs 假星案例 stars/forks ≈ 19，
                                  # 所以 20 是有数据支撑的"嫌疑线"，再低会误伤正常项目。

# 主判据需要的快照年龄下限——不足 7 天的窗口直接退回路径 B，
# 否则"3 天涨 3000"会比"7 天涨 3000"更难触发（语义不一致）
_MIN_HISTORY_AGE_DAYS = 7


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # GitHub API 返回 "2026-04-15T08:00:00Z"
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _count_marketing_hits(readme: str) -> int:
    if not readme:
        return 0
    text = readme.lower()
    hits = 0
    for phrase in _MARKETING_PHRASES:
        if phrase.lower() in text:
            hits += 1
    return hits


def _extract_full_name(item: dict) -> str | None:
    """从 url 反推 owner/repo——比从 id 拆 _ 更安全。"""
    import re
    url = item.get("url") or ""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:[/?#]|$)", url)
    return m.group(1) if m else None


def judge(item: dict, history: dict | None = None) -> str:
    """对单个 GitHub item 返回 verdict_tag。

    history: load_recent_snapshots() 的返回值，形如
             {full_name: {stars, forks, open_issues, snapshot_date, age_days}}。
             路径选择规则：
               - history 不含本仓库 → 走路径 B
               - history 含本仓库但 age_days < 7 → 走路径 B
               - history 含本仓库且 age_days >= 7 → 走路径 A
    """
    meta = item.get("github_meta") or {}
    stars = item.get("stars") or 0
    forks = item.get("forks") or 0
    open_issues = meta.get("open_issues_count") or 0
    pushed_at = _parse_iso(meta.get("pushed_at", ""))
    readme = item.get("_readme_hint") or ""
    stars_today = item.get("stars_today") or 0

    now = datetime.now(timezone.utc)

    # 1. abandoned：仓库长时间没动
    if pushed_at is not None:
        age_days = (now - pushed_at).days
        if age_days > _ABANDONED_DAYS:
            return "abandoned"

    # 2. marketing —— A/B/C 之间是 OR 关系
    full_name = _extract_full_name(item)
    snap = history.get(full_name) if (history and full_name) else None

    if snap is not None and snap.get("age_days", 0) >= _MIN_HISTORY_AGE_DAYS:
        # 路径 A · 主判据：7 天 star 净增 + 提问题的人少
        delta_7d = stars - (snap.get("stars") or 0)
        if (
            delta_7d >= _MARKETING_STAR_DELTA_7D
            and open_issues / max(delta_7d, 1) < _MARKETING_ISSUE_RATIO
        ):
            return "marketing"
    else:
        # 路径 B · 冷启动：用 stars_today 近似
        if (
            stars_today >= _MARKETING_COLD_STARS_TODAY
            and open_issues / max(stars_today, 1) < _MARKETING_COLD_RATIO
        ):
            return "marketing"

    # 路径 C · README 兜底（与 A/B 是 OR 关系）
    if _count_marketing_hits(readme) >= _MARKETING_PHRASE_HITS:
        return "marketing"

    # 3. hype_only：星不少但 fork 比例异常低
    if stars > _HYPE_MIN_STARS and stars / max(forks, 1) > _HYPE_STAR_FORK_RATIO:
        return "hype_only"

    # 4. 兜底
    return "true_use"


def annotate(items: list, history: dict | None = None) -> list:
    """对 source==GitHub 的 trending item 写入 verdict_tag/label/explain/analogy。

    跳过 release 通知（id 以 gh_rel_ 开头）——它们没有 stars/forks/issues，
    不参与 verdict 判定。
    """
    counts = {"true_use": 0, "hype_only": 0, "marketing": 0, "abandoned": 0}
    for item in items:
        if item.get("source") != "GitHub":
            continue
        if (item.get("id") or "").startswith("gh_rel_"):
            continue
        tag = judge(item, history=history)
        meta = VERDICT_META[tag]
        item["verdict_tag"] = tag
        item["verdict_label"] = meta["label"]
        item["verdict_explain"] = meta["explain"]
        item["verdict_analogy"] = meta["analogy"]
        counts[tag] += 1
    print(f"[GitHubVerdict] {counts}")
    return items
