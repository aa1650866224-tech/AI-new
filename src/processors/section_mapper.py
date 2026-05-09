"""
板块映射器：把 collector 输出的 source 字段映射成 4 个板块。

section ∈ {morning, discussion, github, weekend}
- morning:    厂商博客 + 政策 + 中文媒体（一手发布、官方信号）
- discussion: HN + Reddit + X + 个人 blog（社区/个人讨论）
- github:     GitHub Trending（独立板块，verdict 体系保留）
- weekend:    HuggingFace + 其他沉淀型内容
"""

# "今早必读"——一手发布源
MORNING_SOURCES = {
    # 海外厂商
    "OpenAI", "Anthropic", "Google DeepMind", "Meta AI",
    # 国内厂商（待 Firecrawl 就绪后接入）
    "DeepSeek", "智谱", "Kimi", "通义",
    # 政策（待 Firecrawl 就绪后接入）
    "网信办", "EU AI Act", "White House AI EO",
    # 中文媒体
    "量子位", "机器之心",
}

# "圈子在吵"——社区/个人讨论
DISCUSSION_SOURCES = {
    "HackerNews", "Reddit", "X",
    "Simon Willison", "Lilian Weng", "Eugene Yan", "Chip Huyen",
}

# "GitHub 雷达"——独立板块
GITHUB_SOURCES = {"GitHub"}

# "周末再看"——沉淀型内容
WEEKEND_SOURCES = {"HuggingFace"}


def map_section(item: dict) -> str:
    """
    返回该 item 应归属的 section。
    优先用 item._section_hint（collector 设置的提示），其次按 source 查表。
    未知源默认进 discussion（更安全的兜底，比"今早必读"门槛低）。
    """
    hint = item.get("_section_hint")
    if hint in {"morning", "discussion", "github", "weekend"}:
        return hint

    src = item.get("source", "")
    if src in MORNING_SOURCES:
        return "morning"
    if src in DISCUSSION_SOURCES:
        return "discussion"
    if src in GITHUB_SOURCES:
        return "github"
    if src in WEEKEND_SOURCES:
        return "weekend"
    return "discussion"


def assign_sections(items: list) -> list:
    """给每个 item 打 section 字段（in-place）；同时清理 _section_hint 临时字段。"""
    for item in items:
        item["section"] = map_section(item)
        item.pop("_section_hint", None)
    return items


def split_by_section(items: list, limits: dict | None = None) -> dict:
    """
    按 section 切分，返回 {morning: [...], discussion: [...], github: [...], weekend: [...]}。

    limits 例：{morning: 8, discussion: 10}——超过上限的条目丢弃。
    未在 limits 列出的 section 不截断。
    切分前按 heat_score 降序——保证截断保留的是最热条目。
    """
    limits = limits or {}
    out = {"morning": [], "discussion": [], "github": [], "weekend": []}
    items_sorted = sorted(items, key=lambda x: x.get("heat_score", 0), reverse=True)
    for item in items_sorted:
        s = item.get("section", "discussion")
        if s not in out:
            continue
        cap = limits.get(s)
        if cap is None or len(out[s]) < cap:
            out[s].append(item)
    return out
