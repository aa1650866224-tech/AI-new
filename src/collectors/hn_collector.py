import requests
import time
from datetime import datetime, timezone


class HNCollector:
    def __init__(self, config: dict):
        self.cfg = config.get("hackernews", {})
        self.min_score = self.cfg.get("min_score", 50)

    def _get_item(self, sid: int, retries: int = 2) -> dict | None:
        """获取单个 item，带重试和异常保护"""
        for attempt in range(retries + 1):
            try:
                resp = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=30
                )
                return resp.json()
            except Exception:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    return None

    def fetch_top_stories(self, limit: int = 100, keywords_config: dict = None) -> list:
        try:
            resp = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=30)
            ids = resp.json()[:limit]
        except Exception:
            return []
        stories = []
        # 从 keywords.yaml 读取 include/exclude，fallback 到硬编码
        include_kw = [k.lower() for k in keywords_config.get("include", [])] if keywords_config else []
        exclude_kw = [k.lower() for k in keywords_config.get("exclude", [])] if keywords_config else []
        default_ai = ["ai", "llm", "gpt", "chatgpt", "openai", "claude", "machine learning", "deep learning", "neural", "transformer", "llama", "gemini", "deepseek"]
        ai_keywords = include_kw if include_kw else default_ai

        for sid in ids:
            item = self._get_item(sid)
            if not item or item.get("score", 0) < self.min_score:
                continue
            title = item.get("title", "").lower()
            # 排除词过滤
            if any(ex in title for ex in exclude_kw):
                continue
            # 包含词过滤
            if not any(k in title for k in ai_keywords):
                continue
            hn_discussion = f"https://news.ycombinator.com/item?id={item['id']}"
            stories.append({
                "id": str(item["id"]),
                "title": item.get("title", ""),
                "content": item.get("text", item.get("title", "")),
                "url": item.get("url", hn_discussion),
                "discussion_url": hn_discussion,
                "source": "HackerNews",
                "created_at": datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc).isoformat() if item.get("time") else None,
                "likes": item.get("score", 0),
                "retweets": 0,
                "replies": item.get("descendants", 0),
                "author": item.get("by", "unknown"),
                "author_followers": 0
            })
            if len(stories) >= self.cfg.get("max_results", 30):
                break
        return stories

    def fetch(self, keywords_config: dict = None) -> list:
        return self.fetch_top_stories(keywords_config=keywords_config)
