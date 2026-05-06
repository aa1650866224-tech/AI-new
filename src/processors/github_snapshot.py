"""
F6: GitHub 仓库 7 天历史快照

每天采集后把 source==GitHub 的 trending 仓库状态追加到 JSONL 文件。
verdict 判定时读最近 7 天，给 marketing 主路径提供"7 天 star 净增"信号。

文件格式（`data/github_snapshots.jsonl`，每行一个 JSON）：
    {"date":"2026-05-05","full_name":"owner/repo","stars":1234,
     "forks":56,"open_issues":78,"pushed_at":"2026-05-04T12:00:00Z"}

不存历史 release（id 以 gh_rel_ 开头）——它们没有 stars/forks/issues。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone


# 用 url 反推 full_name，避免靠 id 拆 _ 出错
# id 是 f"gh_{full_name.replace('/', '_')}"，无法可逆区分原 owner / repo 中的 _
_URL_RE = re.compile(r"https?://github\.com/([^/]+/[^/]+?)(?:[/?#]|$)")


def _extract_full_name(item: dict) -> str | None:
    url = item.get("url") or ""
    m = _URL_RE.match(url)
    return m.group(1) if m else None


def _today_utc_date() -> datetime:
    """今天的 UTC 0 点，用于算 age_days。"""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_recent_snapshots(snapshot_path: str, days: int = 7) -> dict:
    """读最近 days 天快照，返回 {full_name: 最早一条快照}。

    返回值结构示例：
      {"openai/whisper": {
          "stars": 50000, "forks": 5000, "open_issues": 200,
          "snapshot_date": "2026-04-28", "age_days": 7
      }}

    判定时用 age_days 区分"完整 7 天窗口"和"不足 7 天"——
    judge() 仅在 age_days >= 7 时才走主路径 A。
    """
    if not os.path.exists(snapshot_path):
        return {}

    today_utc = _today_utc_date()
    earliest: dict[str, dict] = {}

    with open(snapshot_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as e:
                print(f"[Snapshot] WARN: skip bad line: {e}")
                continue

            date_str = row.get("date") or ""
            full_name = row.get("full_name") or ""
            if not date_str or not full_name:
                continue

            dt = _parse_date(date_str)
            if dt is None:
                continue
            age_days = (today_utc - dt).days
            if age_days < 0 or age_days > days:
                continue

            existing = earliest.get(full_name)
            if existing is None or age_days > existing["age_days"]:
                # 取"最早"的一条 → age_days 最大
                earliest[full_name] = {
                    "stars": row.get("stars", 0),
                    "forks": row.get("forks", 0),
                    "open_issues": row.get("open_issues", 0),
                    "snapshot_date": date_str,
                    "age_days": age_days,
                }
    return earliest


def append_today_snapshot(snapshot_path: str, github_items: list, today: str) -> None:
    """把今日 trending 仓库追加为 JSONL 行。

    调用方应只传 trending（不要传 release）。本函数也会兜底过滤 gh_rel_。
    幂等性：不去重——main 一天只跑一次，重复行问题忽略。
    """
    os.makedirs(os.path.dirname(snapshot_path) or ".", exist_ok=True)

    with open(snapshot_path, "a", encoding="utf-8") as f:
        for it in github_items:
            if it.get("source") != "GitHub":
                continue
            if (it.get("id") or "").startswith("gh_rel_"):
                continue
            full_name = _extract_full_name(it)
            if not full_name:
                continue
            meta = it.get("github_meta") or {}
            row = {
                "date": today,
                "full_name": full_name,
                "stars": it.get("stars", 0) or 0,
                "forks": it.get("forks", 0) or 0,
                "open_issues": meta.get("open_issues_count", 0) or 0,
                "pushed_at": meta.get("pushed_at", "") or "",
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prune_old_snapshots(snapshot_path: str, max_days: int = 90) -> int:
    """重写文件，只保留最近 max_days 天的记录。返回删除行数。"""
    if not os.path.exists(snapshot_path):
        return 0

    today_utc = _today_utc_date()
    keep: list[str] = []
    removed = 0

    with open(snapshot_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                # 脏行直接丢弃
                removed += 1
                continue
            dt = _parse_date(row.get("date") or "")
            if dt is None:
                removed += 1
                continue
            age = (today_utc - dt).days
            if 0 <= age <= max_days:
                keep.append(line)
            else:
                removed += 1

    if removed == 0:
        return 0

    with open(snapshot_path, "w", encoding="utf-8") as f:
        for line in keep:
            f.write(line + "\n")
    return removed
