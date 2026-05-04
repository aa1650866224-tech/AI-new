import os
import requests
from datetime import datetime, timedelta, timezone


class XCollector:
    def __init__(self, config: dict):
        self.cfg = config.get("x_api", {})
        self.bearer = os.getenv("X_BEARER_TOKEN", self.cfg.get("bearer_token", ""))
        self.headers = {"Authorization": f"Bearer {self.bearer}"}

    def search_recent(self, query: str = "AI OR LLM OR 大模型 OR ChatGPT OR Claude OR OpenAI OR DeepSeek -is:retweet", max_results: int = 50) -> list:
        if not self.bearer:
            print("[X] No bearer token, skipping.")
            return []
        url = "https://api.twitter.com/2/tweets/search/recent"
        start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "query": query,
            "max_results": min(max_results, 100),
            "start_time": start_time,
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "public_metrics,username"
        }
        resp = requests.get(url, headers=self.headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"[X] Error {resp.status_code}: {resp.text}")
            return []
        data = resp.json()
        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        min_likes = self.cfg.get("min_likes", 30)
        min_retweets = self.cfg.get("min_retweets", 5)

        results = []
        for t in tweets:
            metrics = t.get("public_metrics", {})
            likes = metrics.get("like_count", 0)
            retweets = metrics.get("retweet_count", 0)
            if likes < min_likes or retweets < min_retweets:
                continue
            author = users.get(t.get("author_id", ""), {})
            followers = author.get("public_metrics", {}).get("followers_count", 0)
            results.append({
                "id": t["id"],
                "title": t["text"][:120],
                "content": t["text"],
                "url": f"https://x.com/{author.get('username', 'i')}/status/{t['id']}",
                "source": "X",
                "created_at": t["created_at"],
                "likes": likes,
                "retweets": retweets,
                "replies": metrics.get("reply_count", 0),
                "author": author.get("username", "unknown"),
                "author_followers": followers
            })
        return results

    def _build_query(self, keywords_config: dict = None) -> str:
        """根据 keywords.yaml 构建搜索 query（X API Free/Basic 档 query 上限约 512 字符）"""
        include = keywords_config.get("include", []) if keywords_config else []
        exclude = keywords_config.get("exclude", []) if keywords_config else []
        # 核心 AI 关键词（不可裁剪）
        core_terms = ["AI", "LLM", "大模型", "ChatGPT", "Claude", "OpenAI", "DeepSeek"]
        # 用户自定义 include，逐个添加直到接近长度上限
        user_terms = [k for k in include if isinstance(k, str) and k not in core_terms]
        terms = list(core_terms)  # 从核心词开始
        base_query = " OR ".join(terms) + " -is:retweet"
        max_include_len = 480  # 留 32 字符给排除词
        for t in user_terms:
            candidate = " OR ".join(terms + [t]) + " -is:retweet"
            if len(candidate) <= max_include_len:
                terms.append(t)
            else:
                break
        query = " OR ".join(terms) + " -is:retweet"
        # 添加排除词（优先级高，尽量保留）
        for ex in exclude:
            if isinstance(ex, str) and ex.strip():
                addition = f" -\"{ex.strip()}\""
                if len(query) + len(addition) <= 510:
                    query += addition
                else:
                    break
        return query

    def fetch(self, keywords_config: dict = None) -> list:
        query = self._build_query(keywords_config)
        return self.search_recent(query=query, max_results=self.cfg.get("max_results_per_query", 50))
