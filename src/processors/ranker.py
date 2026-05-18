from datetime import datetime, timezone
from dateutil import parser as date_parser


class Ranker:
    def __init__(self, config: dict):
        self.cfg = config.get("ranking", {})

    def _parse_time(self, t) -> datetime:
        """解析时间并统一转为 UTC aware datetime"""
        if isinstance(t, datetime):
            dt = t
        elif isinstance(t, str):
            try:
                dt = date_parser.parse(t)
            except Exception:
                return datetime.now(timezone.utc)
        else:
            return datetime.now(timezone.utc)
        # 转为 UTC aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    def score(self, item: dict) -> float:
        likes = item.get("likes", 0) or 0
        retweets = item.get("retweets", 0) or 0
        replies = item.get("replies", 0) or 0
        stars = item.get("stars", 0) or 0
        forks = item.get("forks", 0) or 0
        followers = item.get("author_followers", 0) or 0

        score = (
            likes * self.cfg.get("like_weight", 1.0)
            + retweets * self.cfg.get("retweet_weight", 2.0)
            + replies * self.cfg.get("reply_weight", 1.5)
            + stars * self.cfg.get("star_weight", 1.0)
            + forks * self.cfg.get("fork_weight", 1.5)
        )

        # 大V加成
        threshold = self.cfg.get("follower_threshold", 100000)
        bonus = self.cfg.get("follower_bonus", 1.2)
        if followers >= threshold:
            score *= bonus

        # 时效衰减（基于 UTC 时间计算）
        created = self._parse_time(item.get("created_at"))
        hours_old = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        decay_start = self.cfg.get("decay_hours", 12)
        decay_rate = self.cfg.get("decay_rate", 0.02)
        if hours_old > decay_start:
            score *= max(0.1, 1 - (hours_old - decay_start) * decay_rate)

        return round(score, 2)

    def rank(self, items: list) -> list:
        for item in items:
            item["heat_score"] = self.score(item)
        sorted_items = sorted(items, key=lambda x: x["heat_score"], reverse=True)
        normalize_score_band(sorted_items)
        return sorted_items


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
