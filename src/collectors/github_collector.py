import os
import re
import requests
from datetime import datetime, timedelta, timezone


class GitHubCollector:
    """
    GitHub 采集器
    - Trending: 爬取 GitHub Trending 页面获取真实热榜（今日新增 star）
    - Releases: 追踪配置仓库的最新 release
    """

    def __init__(self, config: dict):
        self.cfg = config.get("github", {})
        # 支持 GH_PAT 环境变量（GITHUB_* 前缀被 GitHub 保留，用户自定义 PAT 用 GH_PAT）
        token = os.getenv("GH_PAT", os.getenv("GITHUB_TOKEN", ""))
        cfg_token = self.cfg.get("token", "")
        # 过滤掉环境变量占位符（如 ${GH_PAT}）
        self.token = token if token else (cfg_token if cfg_token and not cfg_token.startswith("$") else "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

    # ---- Trending 抓取 ----

    def _parse_trending_page(self, html: str) -> list:
        """解析 GitHub Trending HTML，返回仓库列表"""
        items = []
        # 每个仓库在一个 <article> 中
        articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
        for art in articles:
            # 仓库名：在 <h2> 内的第一个 href="/owner/repo"
            h2 = re.search(r'<h2[^>]*>(.*?)</h2>', art, re.DOTALL)
            if not h2:
                continue
            repo_match = re.search(r'href=\"/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\"', h2.group(1))
            if not repo_match:
                continue
            full_name = repo_match.group(1)
            # 过滤 sponsors 等非仓库链接
            if full_name.startswith(("sponsors/", "login?", "explore/", "settings/")):
                continue

            # 今日新增 star
            stars_match = re.search(r'(\d+(?:,\d+)*)\s+stars?\s+today', art)
            stars_today = int(stars_match.group(1).replace(",", "")) if stars_match else 0

            # 描述
            desc_match = re.search(
                r'<p[^>]*class="[^"]*color-fg-muted[^"]*"[^>]*>(.*?)</p>',
                art, re.DOTALL,
            )
            description = ""
            if desc_match:
                description = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()

            # 语言
            lang_match = re.search(
                r'span[^>]*itemprop="programmingLanguage"[^>]*>([^<]+)</span>',
                art,
            )
            language = lang_match.group(1).strip() if lang_match else ""

            items.append({
                "full_name": full_name,
                "description": description,
                "stars_today": stars_today,
                "language": language,
            })
        return items

    def _enrich_with_api(self, repos: list) -> list:
        """用 GitHub API 补充总 star / fork 数（有 token 时）"""
        if not self.token:
            return repos
        enriched = []
        api_headers = {"Authorization": f"token {self.token}", "Accept": "application/vnd.github.v3+json"}
        for r in repos:
            try:
                resp = requests.get(
                    f"https://api.github.com/repos/{r['full_name']}",
                    headers=api_headers, timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    r["total_stars"] = data.get("stargazers_count", 0)
                    r["forks"] = data.get("forks_count", 0)
                    r["created_at"] = data.get("created_at", "")
                    # F2 新增：用于 verdict 判定的字段
                    r["open_issues_count"] = data.get("open_issues_count", 0)
                    r["pushed_at"] = data.get("pushed_at", "")
                else:
                    r["total_stars"] = 0
                    r["forks"] = 0
                    r["open_issues_count"] = 0
                    r["pushed_at"] = ""
                    r["created_at"] = ""
            except Exception:
                r["total_stars"] = 0
                r["forks"] = 0
                r["open_issues_count"] = 0
                r["pushed_at"] = ""
                r["created_at"] = ""
            enriched.append(r)
        return enriched

    def fetch_trending(self) -> list:
        languages = self.cfg.get("trending_languages", [""])  # "" = all languages
        max_per_lang = self.cfg.get("trending_count", 15)
        all_repos = []

        for lang in languages:
            url = "https://github.com/trending"
            if lang:
                url += f"/{lang}"
            try:
                resp = requests.get(url, headers=self.headers, timeout=30)
                if resp.status_code != 200:
                    print(f"[GitHub] Trending page error {resp.status_code}: {url}")
                    continue
                repos = self._parse_trending_page(resp.text)
                all_repos.extend(repos[:max_per_lang])
            except Exception as e:
                print(f"[GitHub] Trending fetch error: {e}")

        # 去重（多语言可能重复）
        seen = set()
        unique = []
        for r in all_repos:
            if r["full_name"] not in seen:
                seen.add(r["full_name"])
                unique.append(r)

        # API  enrichment
        unique = self._enrich_with_api(unique)

        # 组装为统一 item 格式
        items = []
        for r in unique:
            items.append({
                "id": f"gh_{r['full_name'].replace('/', '_')}",
                "title": f"[仓库] {r['full_name']}: {r['description'] or 'No description'}",
                "content": r["description"] or r["full_name"],
                "url": f"https://github.com/{r['full_name']}",
                "source": "GitHub",
                "created_at": datetime.now(timezone.utc).isoformat(),  # trending 用采集日期 UTC
                "likes": r["stars_today"],          # 今日新增 star 作为 likes
                "retweets": 0,
                "replies": 0,
                "stars": r.get("total_stars", r["stars_today"]),
                "forks": r.get("forks", 0),
                "stars_today": r["stars_today"],    # 保留原始增速
                "author": r["full_name"].split("/")[0],
                "author_followers": 0,
                # F2 verdict 判定所需的元信息（由 _enrich_with_api 填充；无 token 时为空/0）
                "github_meta": {
                    "open_issues_count": r.get("open_issues_count", 0),
                    "pushed_at": r.get("pushed_at", ""),
                    "created_at": r.get("created_at", ""),
                },
            })
        return items

    # ---- Release 追踪 ----

    def fetch_releases(self) -> list:
        if not self.cfg.get("check_releases", True):
            return []
        results = []
        api_headers = {"Authorization": f"token {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        for repo in self.cfg.get("tracked_repos", []):
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            resp = requests.get(url, headers=api_headers, timeout=30)
            if resp.status_code != 200:
                continue
            release = resp.json()
            published = release.get("published_at", "")
            # 只取最近7天的release
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if (datetime.now(pub_dt.tzinfo) - pub_dt).days > 7:
                    continue
            except Exception:
                pass
            results.append({
                "id": f"gh_rel_{release['id']}",
                "title": f"[发布] {repo} {release.get('tag_name', '')}: {release.get('name', '')}",
                "content": release.get("body", "") or release.get("name", ""),
                "url": release.get("html_url", f"https://github.com/{repo}/releases"),
                "source": "GitHub",
                "created_at": published,
                "likes": 0,
                "retweets": 0,
                "replies": 0,
                "stars": 0,
                "forks": 0,
                "author": repo.split("/")[0],
                "author_followers": 100000,
            })
        return results

    def fetch(self) -> list:
        trending = self.fetch_trending()
        releases = self.fetch_releases()
        return trending + releases
