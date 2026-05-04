import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class RSSCollector:
    """
    通用 RSS 采集器
    支持任意标准 RSS 2.0 / Atom feed
    """

    def __init__(self, config: dict):
        self.cfg = config.get("rss", {})
        self.feeds = self.cfg.get("feeds", [])
        self.max_per_feed = self.cfg.get("max_per_feed", 10)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AI-News-Bot/1.0)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }

    def _parse_date(self, date_str: str) -> str:
        """解析各种 RSS 日期格式"""
        if not date_str:
            return datetime.now(timezone.utc).isoformat()
        try:
            # RSS 常用格式: Tue, 28 Apr 2026 06:15:23 +0000
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except Exception:
            pass
        # 尝试 ISO 格式
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            pass
        return datetime.now(timezone.utc).isoformat()

    def _extract_text(self, element, tag: str, ns: dict = None, default: str = "") -> str:
        """安全提取 XML 元素文本"""
        child = element.find(tag, ns)
        return (child.text or default) if child is not None else default

    def _fetch_feed(self, feed: dict) -> list:
        """抓取单个 RSS feed"""
        url = feed.get("url", "")
        source_name = feed.get("name", "RSS")
        if not url:
            return []

        try:
            resp = requests.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                print(f"[RSS] {source_name} error {resp.status_code}: {url}")
                return []

            # 解析 XML
            root = ET.fromstring(resp.content)
            ns = {"content": "http://purl.org/rss/1.0/modules/content/"}

            items = []

            # RSS 2.0 格式: root -> channel -> item
            for channel in root.findall(".//channel"):
                for item in channel.findall("item"):
                    title = self._extract_text(item, "title")
                    link = self._extract_text(item, "link")
                    desc = self._extract_text(item, "description")
                    pub_date = self._extract_text(item, "pubDate")
                    # 优先取 content:encoded，否则取 description
                    content_elem = item.find("content:encoded", ns)
                    content = content_elem.text if content_elem is not None and content_elem.text else desc

                    if not title:
                        continue

                    items.append({
                        "id": f"rss_{hash(link or title) & 0xFFFFFFFF:08x}",
                        "title": title,
                        "content": (content or title)[:1500],
                        "url": link or url,
                        "source": source_name,
                        "created_at": self._parse_date(pub_date),
                        "likes": 0,
                        "retweets": 0,
                        "replies": 0,
                        "author": source_name,
                        "author_followers": 0,
                    })

            # Atom 格式: root -> entry
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = self._extract_text(entry, "{http://www.w3.org/2005/Atom}title")
                link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_elem.get("href", "") if link_elem is not None else ""
                summary = self._extract_text(entry, "{http://www.w3.org/2005/Atom}summary")
                content = self._extract_text(entry, "{http://www.w3.org/2005/Atom}content")
                updated = self._extract_text(entry, "{http://www.w3.org/2005/Atom}updated")
                published = self._extract_text(entry, "{http://www.w3.org/2005/Atom}published")

                if not title:
                    continue

                items.append({
                    "id": f"rss_{hash(link or title) & 0xFFFFFFFF:08x}",
                    "title": title,
                    "content": (content or summary or title)[:1500],
                    "url": link or url,
                    "source": source_name,
                    "created_at": self._parse_date(published or updated),
                    "likes": 0,
                    "retweets": 0,
                    "replies": 0,
                    "author": source_name,
                    "author_followers": 0,
                })

            return items[:self.max_per_feed]

        except ET.ParseError as e:
            print(f"[RSS] {source_name} XML parse error: {e}")
            return []
        except Exception as e:
            print(f"[RSS] {source_name} fetch error: {e}")
            return []

    def fetch(self) -> list:
        all_items = []
        for feed in self.feeds:
            items = self._fetch_feed(feed)
            all_items.extend(items)
        print(f"[RSS] Total {len(all_items)} items from {len(self.feeds)} feeds")
        return all_items
