import os
import sys
import yaml
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 自动加载 .env（如果存在）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 把项目根目录加入路径
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.x_collector import XCollector
from src.collectors.hn_collector import HNCollector
from src.collectors.github_collector import GitHubCollector
from src.collectors.reddit_collector import RedditCollector
from src.collectors.rss_collector import RSSCollector
from src.collectors.producthunt_collector import ProductHuntCollector
from src.processors.dedup import url_dedup, content_dedup, cluster_dedup
from src.processors.ranker import Ranker
from src.processors.summarize import Summarizer
from src.processors.article_fetcher import enrich_items
from src.processors.translator import Translator
from src.processors.github_verdict import annotate as annotate_github_verdict
from src.processors import github_snapshot
from src.storage.json_storage import JsonStorage


SNAPSHOT_PATH_ABS = str(Path(__file__).resolve().parent.parent / "data" / "github_snapshots.jsonl")


def load_config() -> dict:
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    # 加载 keywords.yaml（如果存在）
    keywords_path = PROJECT_ROOT / "config" / "keywords.yaml"
    if keywords_path.exists():
        with open(keywords_path, "r", encoding="utf-8") as f:
            config["keywords"] = yaml.safe_load(f)
    else:
        config["keywords"] = {"include": [], "exclude": []}
    return config


def main():
    print(f"[{datetime.now()}] AI News Assistant starting...")
    config = load_config()

    # 1. 采集（单个来源失败不影响其他来源）
    all_items = []
    sources = [
        ("X", XCollector),
        ("Hacker News", HNCollector),
        ("Reddit", RedditCollector),
        ("RSS feeds", RSSCollector),
        ("Product Hunt", ProductHuntCollector),
        ("GitHub", GitHubCollector),
    ]
    keywords_cfg = config.get("keywords", {})
    total_steps = len(sources) + 4  # 采集 + URL去重 + 评分 + 抓取正文 + 翻译
    for idx, (name, Collector) in enumerate(sources, 1):
        print(f"[{idx}/{total_steps}] Collecting from {name}...")
        try:
            collector = Collector(config)
            # 尝试传入 keywords_config，不支持则回退
            try:
                batch = collector.fetch(keywords_config=keywords_cfg)
            except TypeError:
                batch = collector.fetch()
            all_items.extend(batch)
            print(f"      -> {len(batch)} items (total {len(all_items)})")
        except Exception as e:
            print(f"      -> ERROR: {e}")

    if not all_items:
        print("No items collected. Exiting.")
        return

    # 2. URL去重（在评分前先做简单URL去重，减少后续计算量）
    print(f"[{total_steps - 1}/{total_steps}] URL deduplicating...")
    items = url_dedup(all_items)
    print(f"      -> {len(items)} after URL dedup")

    # 3. 评分排序
    print(f"[{total_steps}/{total_steps}] Ranking & AI processing...")
    ranker = Ranker(config)
    items = ranker.rank(items)

    # 4. 抓取外部链接的完整正文
    print(f"[{total_steps + 1}/{total_steps + 2}] Fetching full article text...")
    items = enrich_items(items)

    # 4.5 GitHub 避坑标签判定（在 _readme_hint 还在 item 上时跑，让标签也能进 summarize prompt）
    # F6：先加载最近 7 天历史快照，主判据（marketing 路径 A）需要它
    history = github_snapshot.load_recent_snapshots(SNAPSHOT_PATH_ABS, days=7)
    items = annotate_github_verdict(items, history=history)

    # 5. 翻译英文正文为中文（长文分段翻译）
    print(f"[{total_steps + 2}/{total_steps + 2}] Translating articles to Chinese...")
    translator = Translator(config)
    items = translator.process_batch(items)

    # 6. 各来源 Top 10（用于来源选项卡）
    # 注：步骤编号延续上面，这里已经是第 11 步之后
    source_names = ["X", "HackerNews", "Reddit", "GitHub", "量子位", "ProductHunt"]
    by_source = {}
    for src in source_names:
        src_items = [item for item in items if item.get("source") == src][:10]
        by_source[src] = src_items
        print(f"      -> {src}: {len(src_items)} items")

    # 7. 统一做 AI 摘要（合并所有需要摘要的条目，避免重复调用 API）
    summarize_ids = set()
    for src_items in by_source.values():
        for item in src_items:
            summarize_ids.add(item["id"])

    items_to_summarize = [item for item in items if item["id"] in summarize_ids]
    print(f"      -> AI summarizing {len(items_to_summarize)} unique items...")

    summarizer = Summarizer(config)
    summarized = summarizer.process_batch(items_to_summarize)
    summarized_map = {item["id"]: item for item in summarized}

    # 用摘要后的数据替换各来源，并确保按热度排序
    for src in source_names:
        src_list = [summarized_map[item["id"]] for item in by_source[src]]
        src_list.sort(key=lambda x: x.get("heat_score", 0), reverse=True)
        by_source[src] = src_list

    # 7. 综合精选：从各来源中优先挑选重磅 → 值得关注 → 了解即可
    top_n = config.get("ranking", {}).get("daily_top_n", 15)
    all_summarized = list(summarized_map.values())

    # 按重要性分层，同层内按热度排序
    def _pick(level: str, limit: int):
        pool = [it for it in all_summarized if it.get("importance") == level]
        pool.sort(key=lambda x: x.get("heat_score", 0), reverse=True)
        return pool[:limit]

    combined_top = _pick("重磅", top_n)
    if len(combined_top) < top_n:
        combined_top.extend(_pick("值得关注", top_n - len(combined_top)))
    if len(combined_top) < top_n:
        combined_top.extend(_pick("了解即可", top_n - len(combined_top)))

    # URL/内容去重（避免同一条在不同来源中出现多次）
    seen = set()
    deduped = []
    for it in combined_top:
        key = it.get("url", it["id"])
        if key not in seen:
            seen.add(key)
            deduped.append(it)
    combined_top = deduped[:top_n]
    print(f"      -> {len(combined_top)} combined top (重磅优先)")

    overview = summarizer.daily_overview(combined_top)

    # 9. 组装日报
    daily_digest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "overview": overview,
        "count": len(combined_top),
        "items": combined_top,
        "by_source": by_source
    }

    # 10. 存储
    storage = JsonStorage(str(PROJECT_ROOT / "data" / "daily"))
    filepath = storage.save(daily_digest)
    print(f"Saved to {filepath}")

    # 11. 复制到 web 目录
    web_data_dir = PROJECT_ROOT / "web" / "data"
    web_path = storage.copy_to_web(web_data_dir=str(web_data_dir))
    if web_path:
        print(f"Copied to web data: {web_path}")

    # 12. 生成日期索引 index.json（供前端读取）
    try:
        import glob, json
        files = sorted([Path(f).stem for f in glob.glob(str(web_data_dir / "*.json")) if Path(f).stem != "index"], reverse=True)
        with open(web_data_dir / "index.json", "w", encoding="utf-8") as f:
            json.dump(files, f, ensure_ascii=False)
        print(f"Updated index.json with {len(files)} dates.")
    except Exception as e:
        print(f"Index update warning: {e}")

    # 13. F6：追加今日 GitHub trending 快照 + 清理 90 天前旧记录
    today_str = datetime.now().strftime("%Y-%m-%d")
    github_items_for_snapshot = [
        it for it in items
        if it.get("source") == "GitHub" and not (it.get("id") or "").startswith("gh_rel_")
    ]
    github_snapshot.append_today_snapshot(SNAPSHOT_PATH_ABS, github_items_for_snapshot, today_str)
    removed = github_snapshot.prune_old_snapshots(SNAPSHOT_PATH_ABS, max_days=90)
    print(f"[Snapshot] appended {len(github_items_for_snapshot)} items, pruned {removed} old rows")

    print("Done.")


if __name__ == "__main__":
    main()
