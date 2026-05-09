"""
F9: GitHub 雷达 7 天滚动累积（独立存档版）

存档文件：data/github_radar.jsonl
  - 每行是一个完整 GitHub item（含 verdict_tag、chinese_summary 等 summarize 后字段）
  - 加 radar_date 字段标记采集日期
  - 不存 release（事件流）

为什么不直接读 web/data/*.json？
  daily JSON 里的 verdict 标签是采集当天用的阈值打的；判定规则一旦升级
  （比如 hype_only 阈值 30→20），历史 daily 里旧标签和新规则混用会污染雷达。
  独立存档保证"从今天起按新规则攒"，调整阈值时清掉存档即可重建。

调用顺序（main.py）：
  1. aggregate_7days(today_items, radar_path, today_str)  # 读存档历史 + 合并今日
  2. append_today(radar_path, today_items, today_str)      # 今日写入存档
  3. prune_old(radar_path, max_days=14)                    # 清理过期
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from src.processors.dedup import normalize_url


def _is_release(item: dict) -> bool:
    return (item.get("id") or "").startswith("gh_rel_")


def _load_radar_recent(radar_path: str, today_str: str, days: int) -> list:
    """读累积存档里最近 days-1 天（不含今天）的 trending 记录。"""
    if not os.path.exists(radar_path):
        return []

    today = datetime.strptime(today_str, "%Y-%m-%d")
    cutoff = today - timedelta(days=days - 1)  # 含 cutoff
    out: list = []
    with open(radar_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as e:
                print(f"[GitHubAggregate] WARN skip bad radar line: {e}")
                continue
            d = row.get("radar_date") or ""
            try:
                d_dt = datetime.strptime(d, "%Y-%m-%d")
            except Exception:
                continue
            if d_dt < cutoff or d_dt >= today:
                continue
            out.append(row)
    return out


def aggregate_7days(
    today_github_items: list,
    radar_path: str,
    today_str: str,
    days: int = 7,
    per_tag_limit: int = 20,
) -> list:
    """合并今日 GitHub items + 累积存档最近 days-1 天的 trending。

    去重：按 normalize_url，今日优先（同一仓库取最新 verdict_tag / heat_score）。
    排序：按 verdict_tag 分组，组内按 heat_score 降序。
    截断：每档保留前 per_tag_limit 条。
    Release：只取今日，不累积。
    """
    today_trending = [it for it in today_github_items if not _is_release(it)]
    today_releases = [it for it in today_github_items if _is_release(it)]

    historical = _load_radar_recent(radar_path, today_str, days)

    merged: list = []
    seen: set = set()
    for it in [*today_trending, *historical]:
        key = normalize_url(it.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(it)

    merged.sort(key=lambda x: (x.get("verdict_tag") or "", -(x.get("heat_score") or 0)))

    counts_seen: dict = {}
    truncated: list = []
    for it in merged:
        tag = it.get("verdict_tag") or "_unknown"
        if counts_seen.get(tag, 0) >= per_tag_limit:
            continue
        counts_seen[tag] = counts_seen.get(tag, 0) + 1
        truncated.append(it)

    print(
        f"[GitHubAggregate] {days}d rolling (cap={per_tag_limit}/tag): {counts_seen} "
        f"(today_trending={len(today_trending)}, history={len(historical)}, +{len(today_releases)} releases)"
    )

    return truncated + today_releases


def append_today(radar_path: str, today_github_items: list, today_str: str) -> int:
    """把今日 trending（已 summarize + verdict）追加到累积存档。
    给每条加 radar_date 字段。Release 不存。返回写入条数。
    """
    os.makedirs(os.path.dirname(radar_path) or ".", exist_ok=True)
    n = 0
    with open(radar_path, "a", encoding="utf-8") as f:
        for it in today_github_items:
            if _is_release(it):
                continue
            row = dict(it)
            row["radar_date"] = today_str
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def prune_old(radar_path: str, max_days: int = 14) -> int:
    """重写存档，只保留最近 max_days 天的记录。返回删除行数。
    max_days 比聚合窗口稍宽，留点缓冲。
    """
    if not os.path.exists(radar_path):
        return 0

    today = datetime.now()
    today = datetime(today.year, today.month, today.day)
    keep: list = []
    removed = 0

    with open(radar_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                removed += 1
                continue
            d = row.get("radar_date") or ""
            try:
                d_dt = datetime.strptime(d, "%Y-%m-%d")
            except Exception:
                removed += 1
                continue
            age = (today - d_dt).days
            if 0 <= age <= max_days:
                keep.append(line)
            else:
                removed += 1

    if removed == 0:
        return 0

    with open(radar_path, "w", encoding="utf-8") as f:
        for line in keep:
            f.write(line + "\n")
    return removed
