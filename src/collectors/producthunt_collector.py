import os
import requests
from datetime import datetime, timezone, timedelta


class ProductHuntCollector:
    """
    Product Hunt 采集器
    使用 Product Hunt GraphQL API v2
    文档: https://api.producthunt.com/v2/docs
    """

    API_URL = "https://api.producthunt.com/v2/api/graphql"

    def __init__(self, config: dict):
        self.cfg = config.get("producthunt", {})
        token = os.getenv("PRODUCTHUNT_TOKEN", "")
        cfg_token = self.cfg.get("token", "")
        # 过滤占位符
        self.token = token if token else (cfg_token if cfg_token and not cfg_token.startswith("$") else "")
        self.max_results = self.cfg.get("max_results", 20)
        self.min_votes = self.cfg.get("min_votes", 20)
        self.ai_topics = set(self.cfg.get("ai_topics", [
            "artificial-intelligence",
            "machine-learning",
            "ai",
            "chatgpt",
            "llm",
            "open-source",
            "developer-tools",
        ]))
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "AI-News-Bot/1.0",
        }

    def _build_query(self) -> str:
        """构建 GraphQL 查询：获取今日热门产品"""
        # 获取昨天0点 UTC（ProductHunt 按太平洋时间发布，UTC 早上7点才换天，取48小时避免空窗）
        yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        posted_after = yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")
        return f'''
        query {{
            posts(first: {self.max_results}, postedAfter: "{posted_after}") {{
                edges {{
                    node {{
                        id
                        name
                        tagline
                        description
                        url
                        website
                        votesCount
                        commentsCount
                        createdAt
                        user {{
                            name
                        }}
                        topics {{
                            edges {{
                                node {{
                                    name
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        '''

    def _is_ai_related(self, post: dict) -> bool:
        """判断产品是否和 AI 相关（通过 topics 或名称/描述关键词）"""
        # 检查 topics
        topics_edges = post.get("topics", {}).get("edges", [])
        topic_names = {t["node"]["name"].lower() for t in topics_edges if "node" in t}
        if self.ai_topics & topic_names:
            return True
        # 检查名称和描述中的关键词
        text = (post.get("name", "") + " " + post.get("tagline", "") + " " + post.get("description", "")).lower()
        ai_keywords = {"ai", "artificial intelligence", "machine learning", "llm", "gpt", "claude",
                       "openai", "deepseek", "model", "neural", "agent", "copilot", "assistant",
                       "chatbot", "generative", "diffusion", "embedding", "rag", "fine-tune"}
        for kw in ai_keywords:
            if kw in text:
                return True
        return False

    def fetch(self) -> list:
        if not self.token:
            print("[ProductHunt] No token configured. Skipping.")
            print("  -> Get a free API token at https://www.producthunt.com/v2/oauth/applications")
            return []

        query = self._build_query()
        try:
            resp = requests.post(
                self.API_URL,
                headers=self.headers,
                json={"query": query},
                timeout=30,
            )
            if resp.status_code == 401:
                print("[ProductHunt] 401 Unauthorized - Token invalid or expired.")
                return []
            if resp.status_code != 200:
                print(f"[ProductHunt] API error {resp.status_code}: {resp.text[:300]}")
                return []

            data = resp.json()
            if "errors" in data:
                print(f"[ProductHunt] GraphQL error: {data['errors']}")
                return []

            edges = data.get("data", {}).get("posts", {}).get("edges", [])
            items = []
            for edge in edges:
                node = edge.get("node", {})
                if not node:
                    continue

                votes = node.get("votesCount", 0)
                if votes < self.min_votes:
                    continue

                if not self._is_ai_related(node):
                    continue

                title = node.get("name", "")
                tagline = node.get("tagline", "")
                desc = node.get("description", "")
                content = "\n".join(filter(None, [tagline, desc]))
                if not content:
                    content = title

                created = node.get("createdAt", "")
                author = node.get("user", {}).get("name", "unknown")

                items.append({
                    "id": f"ph_{node['id']}",
                    "title": title,
                    "content": content[:1200],
                    "url": node.get("website") or node.get("url", ""),
                    "source": "ProductHunt",
                    "created_at": created or datetime.now().isoformat(),
                    "likes": votes,
                    "retweets": 0,
                    "replies": node.get("commentsCount", 0),
                    "author": author,
                    "author_followers": 0,
                })

            print(f"[ProductHunt] -> {len(items)} AI-related items")
            return items

        except Exception as e:
            print(f"[ProductHunt] Fetch error: {e}")
            return []
