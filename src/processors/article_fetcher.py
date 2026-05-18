"""
文章正文抓取模块
使用 trafilatura 从原始 URL 抓取完整正文内容，带本地缓存和降级机制。
对 arxiv 走官方 API 拿 abstract（不走 trafilatura）。
"""
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura

# 已知抓不了或不需要抓的域名黑名单
SKIP_DOMAINS = {
    "twitter.com", "x.com", "t.co",
    "github.com", "gist.github.com",
    "huggingface.co",  # HF 模型页面：保留 hf_collector 写入的中文模型卡片，不让 trafilatura 抓回英文 README 覆盖
    "youtube.com", "youtu.be",
    "reddit.com", "redd.it",
    "producthunt.com",
    "docs.google.com", "drive.google.com",
    "medium.com",  # 反爬较严，先放黑名单观察
}


def _get_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _cache_path(url: str, cache_dir: Path) -> Path:
    h = _url_hash(url)
    return cache_dir / f"{h}.json"


def _load_cache(url: str, cache_dir: Path) -> str | None:
    path = _cache_path(url, cache_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("text")
    except Exception:
        return None


def _save_cache(url: str, text: str, cache_dir: Path):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url, cache_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "text": text}, f, ensure_ascii=False)
    except Exception:
        pass


def should_fetch(url: str) -> bool:
    """判断该 URL 是否值得抓取（用于常规 enrich：写入 content 字段）。"""
    if not url or not url.startswith("http"):
        return False
    domain = _get_domain(url)
    return domain not in SKIP_DOMAINS


# trafilatura 抓回正文末尾常见的页脚 marker——版权声明、相关推荐链接列表等
# 仅在文章后半部识别，避免误切正文中字面引用的 "版权所有"
_FOOTER_MARKERS = (
    "*版权所有",            # 量子位等中文媒体常见的斜体版权声明
    "版权所有，未经授权",
    "未经授权不得以任何形式",
    "*相关阅读*", "*相关推荐*", "*延伸阅读*", "*推荐阅读*",
    "## 相关阅读", "## 相关推荐", "## 推荐阅读", "## 延伸阅读",
    "**相关阅读**", "**相关推荐**",
)


def _clean_article_footer(text: str) -> str:
    """切除文章末尾的版权声明 / 相关推荐链接列表等噪声。
    仅扫描后半部，避免误伤正文中的字面引用。
    """
    if not text:
        return text
    cut_search_start = len(text) // 2
    earliest = len(text)
    for marker in _FOOTER_MARKERS:
        idx = text.find(marker, cut_search_start)
        if 0 <= idx < earliest:
            earliest = idx
    if earliest < len(text):
        return text[:earliest].rstrip()
    return text


# 量子位文章固定开头模板：
#   Jim Fan全新暴论出炉      ← 副标题（每篇不同，不死匹配）
#   henry 发自 凹非寺        ← 「XX 发自 YY」签发地点
#   量子位 | 公众号 QbitAI   ← 固定媒体署名
# 仅对量子位域名生效，不做通用启发式（避免误伤其他源）
_QBITAI_BYLINE_RE = re.compile(r"^\S+\s*发自\s*\S+\s*$")


def _clean_article_header(text: str, source_url: str) -> str:
    """仅对 qbitai 域名清理开头 byline 模板。
    在前 5 段范围内查找 marker，找到就把 marker 段及之前所有段一起砍掉。
    取最靠后的 marker 位置，避免漏砍中间一行。
    """
    if not text or not source_url:
        return text
    if "qbitai" not in source_url.lower():
        return text

    paragraphs = text.split("\n\n")
    scan_limit = min(5, len(paragraphs))
    cut_idx = -1
    for i in range(scan_limit):
        p = paragraphs[i].strip()
        if not p:
            continue
        if _QBITAI_BYLINE_RE.match(p):
            cut_idx = i
            continue
        if "公众号 QbitAI" in p or "公众号QbitAI" in p:
            cut_idx = i
            continue
        if p == "量子位":
            cut_idx = i
            continue

    if cut_idx >= 0:
        return "\n\n".join(paragraphs[cut_idx + 1:]).lstrip()
    return text


# arxiv URL 形如：
#   https://arxiv.org/abs/2509.00462
#   https://arxiv.org/abs/2509.00462v2
#   https://arxiv.org/pdf/2509.00462.pdf
#   https://arxiv.org/abs/cs.AI/0501001  (旧格式)
_ARXIV_ID_RE_NEW = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_ARXIV_ID_RE_OLD = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I)


def _arxiv_id_from_url(url: str) -> str | None:
    m = _ARXIV_ID_RE_NEW.search(url)
    if m:
        return m.group(1)
    m = _ARXIV_ID_RE_OLD.search(url)
    if m:
        return m.group(1)
    return None


def _fetch_arxiv(url: str, timeout: int = 15) -> str | None:
    """从 arxiv 官方 API 拿标题、作者、abstract，拼成 markdown 文本"""
    aid = _arxiv_id_from_url(url)
    if not aid:
        return None
    api = f"https://export.arxiv.org/api/query?id_list={aid}"
    try:
        resp = requests.get(api, timeout=timeout)
        if resp.status_code != 200:
            return None
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        title = re.sub(r"\s+", " ", title)
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        authors = [
            (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]
        authors = [a for a in authors if a]
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()

        if not summary:
            return None

        parts = []
        if title:
            parts.append(f"# {title}")
        meta_line = []
        if authors:
            shown = ", ".join(authors[:8]) + (" 等" if len(authors) > 8 else "")
            meta_line.append(f"**Authors:** {shown}")
        if published:
            meta_line.append(f"**Published:** {published[:10]}")
        if meta_line:
            parts.append(" · ".join(meta_line))
        parts.append(f"## Abstract\n\n{summary}")
        parts.append(f"[arXiv:{aid}](https://arxiv.org/abs/{aid})")
        return "\n\n".join(parts)
    except Exception:
        return None


def fetch_article_text(url: str, cache_dir: Path | None = None, timeout: int = 15) -> str | None:
    """
    从 URL 抓取文章正文。
    返回提取到的纯文本正文，或 None（抓取失败）。
    """
    if not should_fetch(url):
        return None

    # 缓存目录
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "article_cache"
    cache_dir = Path(cache_dir)

    # 尝试读缓存（旧 cache 没经过 header/footer 清洗，加载时统一过一遍）
    cached = _load_cache(url, cache_dir)
    if cached is not None:
        return _clean_article_footer(_clean_article_header(cached, url))

    # arxiv 走官方 API（abstract 页 trafilatura 抓不全，PDF 也抓不了）
    if _get_domain(url) == "arxiv.org":
        text = _fetch_arxiv(url)
        if text:
            _save_cache(url, text, cache_dir)
        return text

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return None

        # 反爬简单检测
        text_lower = resp.text.lower()[:1500]
        if "cloudflare" in text_lower and "challenge" in text_lower:
            return None
        if "captcha" in text_lower:
            return None
        if resp.status_code == 403:
            return None

        # trafilatura 提取正文（markdown 输出，保留图片和链接）
        extracted = trafilatura.extract(
            resp.text,
            url=url,  # 用于把相对图片/链接转换成绝对 URL
            output_format="markdown",
            include_comments=False,
            include_tables=False,
            include_images=True,
            include_links=True,
            no_fallback=False,
        )

        if not extracted or len(extracted.strip()) < 200:
            return None

        # 切除量子位 byline header + 版权声明/相关推荐 footer
        extracted = _clean_article_header(extracted, url)
        extracted = _clean_article_footer(extracted)

        # 截断过长内容（超过 5 万字直接截断，避免 JSON 过大）
        MAX_LEN = 50000
        if len(extracted) > MAX_LEN:
            extracted = extracted[:MAX_LEN] + "\n\n[内容过长，已截断]"

        _save_cache(url, extracted, cache_dir)
        return extracted

    except Exception:
        return None


def enrich_items(items: list, cache_dir: Path | None = None) -> list:
    """
    对 items 列表批量抓取原文正文，填充到 content 字段。
    如果抓取失败，保留原有 content。
    """
    success = 0
    skip = 0
    fail = 0

    for item in items:
        url = item.get("url", "")

        original_content = item.get("content", "") or ""

        # 已经有足够长的内容，跳过
        if len(original_content.strip()) >= 2000:
            skip += 1
            continue

        if not should_fetch(url):
            skip += 1
            continue

        fetched = fetch_article_text(url, cache_dir=cache_dir)
        if fetched and len(fetched.strip()) > len(original_content.strip()):
            item["content"] = fetched.strip()
            item["content_fetched"] = True  # 标记为抓取得到
            success += 1
        else:
            fail += 1

    total = len(items)
    print(
        f"[ArticleFetcher] total={total} | success={success} | skip={skip} | fail={fail}"
    )
    return items
