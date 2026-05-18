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

from src.collectors.hn_collector import HNCollector
from src.collectors.reddit_collector import RedditCollector
from src.collectors.rss_collector import RSSCollector
from src.collectors.hf_collector import HFCollector
from src.processors.dedup import url_dedup, content_dedup, cluster_dedup
from src.processors.ranker import Ranker
from src.processors.summarize import Summarizer
from src.processors.article_fetcher import enrich_items
from src.processors.section_mapper import assign_sections, split_by_section
from src.storage.json_storage import JsonStorage


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
        ("Hacker News", HNCollector),
        ("Reddit", RedditCollector),
        ("RSS feeds", RSSCollector),
        ("HuggingFace", HFCollector),
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

    # 5. 板块映射（按 source 给每条打 section 字段）
    items = assign_sections(items)

    # 7. 板块切分 + cap（节约后续 AI 摘要的 token——cap 之外的不摘要）
    sections_cfg = config.get("sections", {})
    section_limits = {
        "morning": sections_cfg.get("morning_max", 8),
        "discussion": sections_cfg.get("discussion_max", 10),
        # github / weekend 不 cap
    }
    by_section = split_by_section(items, limits=section_limits)
    for s, lst in by_section.items():
        print(f"      -> {s}: {len(lst)} items (cap={section_limits.get(s, '-')})")

    # 8. AI 摘要（只对板块切分后的 items 做，节约 LLM 调用）
    items_to_summarize = []
    for section_items in by_section.values():
        items_to_summarize.extend(section_items)
    print(f"      -> AI summarizing {len(items_to_summarize)} items...")
    summarizer = Summarizer(config)
    summarizer.process_batch(items_to_summarize)  # in-place 修改，by_section 内 dict 同步更新

    # 10. 防御性清场：移除残留的 importance 和临时字段
    # （summarize.process_batch 已清 importance，这里是双重保险，且清掉 _readme_hint）
    for section_items in by_section.values():
        for item in section_items:
            item.pop("importance", None)
            item.pop("_readme_hint", None)

    # 11. 日报总览（用 morning + discussion 前 10 条做素材，最能代表当日重要新闻）
    overview_pool = (by_section["morning"] + by_section["discussion"])[:10]
    overview = summarizer.daily_overview(overview_pool)

    # 12. 组装日报（新结构 - by_section 替代 items + by_source）
    daily_digest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "overview": overview,
        "by_section": by_section,
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

    print("Done.")


if __name__ == "__main__":
    main()
