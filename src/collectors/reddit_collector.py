import requests
from datetime import datetime, timezone


class RedditCollector:
    """
    Reddit 采集器
    使用 Reddit JSON API（无需认证，公开子版块即可访问）
    """

    def __init__(self, config: dict):
        self.cfg = config.get("reddit", {})
        self.subreddits = self.cfg.get("subreddits", ["MachineLearning"])
        self.max_per_sub = self.cfg.get("max_results_per_sub", 15)
        self.min_score = self.cfg.get("min_score", 10)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AI-News-Bot/1.0)",
            "Accept": "application/json",
        }

    def _fetch_subreddit(self, sub: str, sort: str = "hot") -> list:
        """抓取单个子版块的帖子列表"""
        url = f"https://www.reddit.com/r/{sub}/{sort}.json"
        params = {"limit": self.max_per_sub}
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=20)
            if resp.status_code == 429:
                print(f"[Reddit] 429 Too Many Requests for r/{sub}, will retry with backoff")
                return []
            if resp.status_code != 200:
                print(f"[Reddit] r/{sub} error {resp.status_code}: {resp.text[:200]}")
                return []
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            items = []
            for child in children:
                d = child.get("data", {})
                # 过滤置顶帖、低分帖
                if d.get("stickied") or d.get("pinned"):
                    continue
                score = d.get("score", 0)
                if score < self.min_score:
                    continue

                title = d.get("title", "").strip()
                selftext = d.get("selftext", "").strip()
                url_field = d.get("url", "")
                permalink = d.get("permalink", "")
                # 外链优先用外部链接；self post 用 permalink
                item_url = url_field if url_field and not url_field.startswith("/") else f"https://www.reddit.com{permalink}"
                # 如果 selftext 太长截断
                content = selftext[:1200] if selftext else title
                created_utc = d.get("created_utc", 0)
                created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat() if created_utc else datetime.now().isoformat()

                items.append({
                    "id": f"rd_{d.get('id', '')}",
                    "title": title,
                    "content": content,
                    "url": item_url,
                    "source": "Reddit",
                    "subreddit": sub,
                    "created_at": created_dt,
                    "likes": score,
                    "retweets": 0,
                    "replies": d.get("num_comments", 0),
                    "author": d.get("author", "unknown"),
                    "author_followers": 0,
                })
            return items
        except Exception as e:
            print(f"[Reddit] r/{sub} fetch error: {e}")
            return []

    def fetch(self) -> list:
        all_items = []
        for sub in self.subreddits:
            items = self._fetch_subreddit(sub)
            all_items.extend(items)
        print(f"[Reddit] Total {len(all_items)} items from {len(self.subreddits)} subreddits")
        return all_items
