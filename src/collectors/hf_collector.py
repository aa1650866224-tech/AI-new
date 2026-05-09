"""
HuggingFace Trending Models 采集。
HF API 端点：/api/models?sort={trendingScore|downloads|likes}&direction=-1&limit=N&filter=...
策略：抓 text-generation 类模型按 trendingScore 排序，每条作为一个 item。
"""
import requests
from datetime import datetime, timezone


class HFCollector:
    def __init__(self, config: dict):
        self.cfg = config.get("huggingface", {})
        self.max_results = self.cfg.get("max_results", 15)
        self.sort_by = self.cfg.get("sort", "trendingScore")  # trendingScore / downloads / likes
        self.endpoint = "https://huggingface.co/api/models"

    def fetch(self) -> list:
        params = {
            "sort": self.sort_by,
            "direction": -1,
            "limit": self.max_results,
            "filter": "text-generation",
        }
        try:
            resp = requests.get(self.endpoint, params=params, timeout=20)
            resp.raise_for_status()
            models = resp.json()
        except Exception as e:
            print(f"[HF] fetch error: {e}")
            return []

        items = []
        for m in models:
            model_id = m.get("modelId") or m.get("id") or ""
            if not model_id:
                continue
            likes = m.get("likes", 0)
            downloads = m.get("downloads", 0)
            updated = m.get("lastModified") or m.get("createdAt")
            tags = ", ".join(m.get("tags", [])[:5])
            items.append({
                "id": f"hf_{hash(model_id) & 0xFFFFFFFF:08x}",
                "title": model_id,
                "content": f"HuggingFace 模型: {model_id}\n下载: {downloads} | 点赞: {likes}\n标签: {tags}",
                "url": f"https://huggingface.co/{model_id}",
                "source": "HuggingFace",
                "created_at": updated or datetime.now(timezone.utc).isoformat(),
                "likes": likes,
                "retweets": 0,
                "replies": 0,
                "author": model_id.split("/")[0] if "/" in model_id else "HuggingFace",
                "author_followers": 0,
                "stars": likes,
                "_section_hint": "weekend",
            })
        print(f"[HF] {len(items)} trending models")
        return items
