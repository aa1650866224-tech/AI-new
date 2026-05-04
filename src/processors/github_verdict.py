"""
F2: GitHub 项目"避坑标签"判定器

输入：collector 拿回来的 GitHub item（需要 github_meta 字段 + _readme_hint）
输出：在 item 上添加 verdict_tag / verdict_label / verdict_explain / verdict_analogy

判定优先级（从上往下，命中即停）：
  1. abandoned   ：pushed_at 距今 > 90 天
  2. marketing   ：星暴涨 / 营销词密度高
  3. hype_only   ：星很多但 fork 比例异常低
  4. true_use    ：默认兜底

所有阈值都是初始值，跑两周后根据实际数据再调。
"""
from __future__ import annotations

from datetime import datetime, timezone


# ---- 4 个标签的元信息（PRD 表格） ----
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
        "explain": "星数短期暴涨 + README 充斥夸张话术",
        "analogy": "像短视频里「3 天瘦 10 斤」那种话术",
    },
    "abandoned": {
        "label": "⚫ 已停摆",
        "explain": "几个月没人维护了",
        "analogy": "像招牌还挂着但已经关门的店",
    },
}

# README 里命中即记一次的"营销词"（中英混合）
# TODO 调优：上线后定期补充新出现的吹嘘话术
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

# 阈值集中在这里，方便调优
# TODO 调优：上线 1-2 周后根据 verdict_tag 分布人工校准
_ABANDONED_DAYS = 90        # pushed_at 超过 N 天没动 → abandoned
_MARKETING_PHRASE_HITS = 3  # README 命中不同营销词 ≥ N 个 → marketing
_HYPE_STAR_FORK_RATIO = 100 # stars / max(forks, 1) > N 且 stars > 阈值 → hype_only
_HYPE_MIN_STARS = 500


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


def judge(item: dict) -> str:
    """对单个 GitHub item 返回 verdict_tag。"""
    meta = item.get("github_meta") or {}
    stars = item.get("stars") or 0
    forks = item.get("forks") or 0
    open_issues = meta.get("open_issues_count") or 0
    pushed_at = _parse_iso(meta.get("pushed_at", ""))
    readme = item.get("_readme_hint") or ""

    now = datetime.now(timezone.utc)

    # 1. abandoned：仓库长时间没动
    if pushed_at is not None:
        age_days = (now - pushed_at).days
        if age_days > _ABANDONED_DAYS:
            return "abandoned"

    # 2. marketing
    #    PRD 原条件 a 需要 recent_stars_7d，本期暂未引入；用 stars_today 近似——
    #    今日新增 star 高且几乎没有 issue 互动 = 流量来得太突然
    stars_today = item.get("stars_today") or 0
    if stars_today >= 500 and stars_today / max(open_issues, 1) > 200:
        return "marketing"
    if _count_marketing_hits(readme) >= _MARKETING_PHRASE_HITS:
        return "marketing"

    # 3. hype_only：星不少但 fork 比例异常低
    if stars > _HYPE_MIN_STARS and stars / max(forks, 1) > _HYPE_STAR_FORK_RATIO:
        return "hype_only"

    # 4. 兜底
    return "true_use"


def annotate(items: list) -> list:
    """对 source==GitHub 的 item 写入 verdict_tag/label/explain/analogy。"""
    counts = {"true_use": 0, "hype_only": 0, "marketing": 0, "abandoned": 0}
    for item in items:
        if item.get("source") != "GitHub":
            continue
        tag = judge(item)
        meta = VERDICT_META[tag]
        item["verdict_tag"] = tag
        item["verdict_label"] = meta["label"]
        item["verdict_explain"] = meta["explain"]
        item["verdict_analogy"] = meta["analogy"]
        counts[tag] += 1
    print(f"[GitHubVerdict] {counts}")
    return items
