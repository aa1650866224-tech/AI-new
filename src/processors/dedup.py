import re
import hashlib
from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def url_dedup(items: list) -> list:
    seen = set()
    unique = []
    for item in items:
        url = item.get("url", "")
        norm = normalize_url(url)
        if norm and norm in seen:
            continue
        if norm:
            seen.add(norm)
        unique.append(item)
    return unique


def simple_text_hash(text: str) -> str:
    text = re.sub(r"\s+", "", text.lower())
    text = re.sub(r"[^\u4e00-\u9fa5a-z0-9]", "", text)
    return hashlib.md5(text[:200].encode()).hexdigest()


def content_dedup(items: list, threshold_chars: int = 50) -> list:
    """基于文本相似度的简单去重（保留热度高的）"""
    items_sorted = sorted(items, key=lambda x: x.get("heat_score", 0), reverse=True)
    seen_hashes = set()
    unique = []
    for item in items_sorted:
        text = item.get("title", "") + " " + item.get("content", "") + " " + item.get("summary", "")
        h = simple_text_hash(text)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        unique.append(item)
    return unique


def cluster_dedup(items: list, max_per_cluster: int = 2) -> list:
    """简单关键词聚类去重，同一类事件最多保留 max_per_cluster 条"""
    clusters = {}
    result = []
    for item in sorted(items, key=lambda x: x.get("heat_score", 0), reverse=True):
        text = (item.get("title", "") + " " + item.get("content", "")).lower()
        cluster_key = None
        for keyword in ["openai", "gpt", "claude", "anthropic", "gemini", "google", "llama", "meta", "deepseek", "mistral", "microsoft", "nvidia"]:
            if keyword in text:
                cluster_key = keyword
                break
        if cluster_key is None:
            cluster_key = "_other"
        clusters.setdefault(cluster_key, 0)
        if clusters[cluster_key] < max_per_cluster:
            clusters[cluster_key] += 1
            result.append(item)
    return result
