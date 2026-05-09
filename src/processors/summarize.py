import os
import json
import requests


def _extract_json_obj(raw: str) -> str:
    """从 LLM 输出中提取 JSON 对象串：找第一个 { 到最后一个 }。
    比 .replace('json','') 安全——不会吃掉 JSON 字符串值里的字面 'json'。
    找不到时原样返回，交给 json.loads 自然抛错走 fallback。
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return raw[start:end + 1]
    return raw


class Summarizer:
    def __init__(self, config: dict):
        self.cfg = config.get("deepseek", {})
        self.api_key = os.getenv("DEEPSEEK_API_KEY", self.cfg.get("api_key", ""))
        self.api_base = self.cfg.get("api_base", "https://api.deepseek.com/v1")
        self.model = self.cfg.get("model", "deepseek-chat")

    def _call(self, messages: list, temperature: float = 0.7) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def summarize_item(self, title: str, content: str, source: str) -> dict:
        prompt = f"""你是一位专业的AI新闻编辑。请对以下{source}内容进行深度分析，并严格按JSON格式返回，不要包含任何其他文字。

注意 chinese_summary 与 editor_note 是两个独立字段，分工严格：
- chinese_summary：客观新闻体，只陈述事实
- editor_note：主观编辑视角，给判断

{{
  "chinese_title": "用一句话概括的中文标题（不超过30字）",
  "chinese_summary": "60-80字的客观新闻摘要，最多两句话。只陈述事实，不做评价。必须包含：核心事件 + 关键数字/产品名/版本号。禁止『值得关注』『引发讨论』『令人瞩目』『重磅』等评价性套话，禁止任何形容词式判断。",
  "original_excerpt": "从原文中摘抄出2-3句最关键的原话（保持原文语言，不要翻译），帮助读者快速了解原文核心。如果原文是代码或极短内容，则直接摘录全部",
  "category": "从[模型发布, 产品更新, 技术论文, 行业观点, 投资融资, 开源工具]中选择最贴合的一个",
  "editor_note": "80-120字的编辑按语，主观视角。回答『读者为什么应该花时间看这条』——可以是判断（这是真突破还是炒作）、对比（和 X 公司同类产品差在哪）、提醒（哪个细节大家都没注意到）、祛魅（说人话指出哪里其实不新）。禁止重复 chinese_summary 已经讲过的事实，禁止场面话。",
  "sentiment": "整体情绪倾向：positive / neutral / negative"
}}

原文标题：{title}
原文内容：{content}
"""
        raw = self._call([{"role": "user", "content": prompt}], temperature=0.3)
        try:
            data = json.loads(_extract_json_obj(raw))
        except Exception:
            data = {
                "chinese_title": title[:50],
                "chinese_summary": raw[:300],
                "original_excerpt": content[:300] if content else "",
                "category": "行业观点",
                "editor_note": "（按语生成失败，模型返回未通过 JSON 解析）",
                "sentiment": "neutral"
            }
        # 即使 LLM 错误返回了 importance，显式清掉——本架构不再使用该字段
        data.pop("importance", None)
        return data

    def summarize_github_repo(
        self,
        title: str,
        description: str,
        readme_hint: str,
        verdict_tag: str = "",
    ) -> dict:
        """GitHub 仓库专属摘要：祛魅式四段输出。

        与通用 summarize_item 的核心差异：
        - 不输出 importance（被 verdict_tag 替代，避免"重磅/值得关注"焦虑文案）
        - 不输出 repo_card（旧版"项目卡片"已废弃）
        - 输出 verdict.{category_tag, who_should_care, prerequisites, similar_projects}
        - similar_projects 允许返回空数组——AI 圈很多新方向没成熟竞品，强行让 LLM 找会编造
        """
        verdict_hint = (
            f"\n参考：项目已被规则引擎初步打上 `{verdict_tag}` 标签（仅供参考，不必盲从）。"
            if verdict_tag else ""
        )

        prompt = f"""你是一位有批判精神的开源项目编辑。下面是一个 GitHub 仓库的元信息和 README 片段。
你的任务不是替项目做营销，而是帮中文读者冷静判断"这个项目值不值得我现在 care"。

请严格按 JSON 格式返回，不要包含任何其他文字：
{{
  "chinese_title": "用一句话说清这是什么项目，≤30 字",
  "chinese_summary": "用 1-2 句中文给出项目整体定位，作为综合列表卡片摘要使用，避免使用「爆火 / 狂揽 / 横扫 / 革命性」等情绪化词，用「新出现 / 又一个 / 主打」等中性表达",
  "verdict": {{
    "category_tag": "四选一：真新方向 / 老问题的新工具 / 换皮再卷一遍 / Demo 级想法",
    "who_should_care": "分人群说话，明确告诉读者『如果你是 X，建议 Y；如果你是 Z，可以 W』。≤80 字。允许说『没必要折腾』『等几个月看是否还活着』",
    "prerequisites": "用之前需要满足什么：是否需要 GPU / API key / 特定系统 / 英文文档能力 / 编程基础。≤60 字。没有特殊要求就直接写『无特殊要求』",
    "similar_projects": ["1-2 个成熟竞品的项目名；如确实没有合适的，就返回空数组 []，不要编造"]
  }},
  "original_excerpt": "从 README 中摘抄 1-2 句最能体现项目定位的英文原文（保持原文，不翻译）",
  "category": "从[模型发布, 产品更新, 技术论文, 行业观点, 投资融资, 开源工具]中选择最贴合的一个，多数 GitHub 仓库属于「开源工具」",
  "sentiment": "整体情绪倾向：positive / neutral / negative"
}}

判断 category_tag 的参考：
- 真新方向：解决了过去无成熟方案的问题，或在某个能力上有质的突破
- 老问题的新工具：问题不新，已有 langchain / Cursor / ComfyUI 等成熟方案，本项目是新尝试
- 换皮再卷一遍：本质是已有项目的微调 / fork / 套壳，没有实质增量
- Demo 级想法：仓库还很早期，README 主要是 demo 截图，没有可靠的稳定版

要求：
- 如果项目确实有突破或扎实价值，就如实说，不要为了显得"批判"而硬唱衰
- similar_projects 找不到就返回 []，**严禁编造**不存在的项目名
- 不要罗列安装命令、不要翻译 README 段落
{verdict_hint}

仓库标题：{title}
仓库一句话描述：{description}
README 片段（已截取头部）：
{readme_hint}
"""
        raw = self._call([{"role": "user", "content": prompt}], temperature=0.3)
        try:
            data = json.loads(_extract_json_obj(raw))
        except Exception:
            data = {
                "chinese_title": title[:50],
                "chinese_summary": raw[:300],
                "verdict": {
                    "category_tag": "Demo 级想法",
                    "who_should_care": "AI 摘要解析失败，建议直接看 README。",
                    "prerequisites": "无特殊要求",
                    "similar_projects": [],
                },
                "original_excerpt": (readme_hint or description)[:300],
                "category": "开源工具",
                "sentiment": "neutral",
            }
        # 兜底：保证 verdict 子字段齐全
        v = data.get("verdict") or {}
        data["verdict"] = {
            "category_tag": v.get("category_tag", "Demo 级想法"),
            "who_should_care": v.get("who_should_care", ""),
            "prerequisites": v.get("prerequisites", "无特殊要求"),
            "similar_projects": v.get("similar_projects", []) if isinstance(v.get("similar_projects"), list) else [],
        }
        # 显式移除 importance / repo_card 字段（即使 LLM 错误返回也清掉）
        data.pop("importance", None)
        data.pop("repo_card", None)
        return data

    def daily_overview(self, items: list) -> str:
        if not items:
            return "今日暂无重要AI资讯。"
        summaries = []
        for i, item in enumerate(items[:15], 1):
            t = item.get("chinese_title", item.get("title", ""))
            s = item.get("chinese_summary", "")[:80]
            summaries.append(f"{i}. {t}：{s}")
        prompt = f"""基于以下今日Top AI资讯摘要，用一段流畅、有洞察力的中文（200字以内）总结"今日AI速览"，突出最重要趋势。

文案要求：
- 涉及 GitHub 开源项目时，不要用「爆火 / 狂揽 / 横扫 / 收割 / 革命性」等夸张话术，用「新出现 / 又一个 / 新尝试」等中性表达
- 关注事件本身的影响和趋势，而不是单纯的热度数字
- 不要堆砌"重磅 / 值得关注"等评级词

""" + "\n".join(summaries)
        return self._call([{"role": "user", "content": prompt}], temperature=0.7)

    def process_batch(self, items: list) -> list:
        for item in items:
            # GitHub 仓库（无论是否拿到 README）都走专属祛魅 prompt
            if item.get("source") == "GitHub" and item.get("verdict_tag"):
                readme_hint = item.get("_readme_hint", "") or ""
                result = self.summarize_github_repo(
                    item.get("title", ""),
                    item.get("content", ""),  # content 仍是 description（一句话）
                    readme_hint,
                    verdict_tag=item.get("verdict_tag", ""),
                )
                item.update(result)
                # 摘要素材用完即扔，不写入最终 JSON
                item.pop("_readme_hint", None)
                continue

            # 优先使用中文翻译内容做摘要，更准确；否则 fallback 到原文
            text = item.get("chinese_content") or item.get("content", "")
            result = self.summarize_item(
                item.get("title", ""),
                text,
                item.get("source", "未知")
            )
            item.update(result)

        # 全局清场：本架构不再使用 importance 字段（综合精选已砍除）
        for item in items:
            item.pop("importance", None)
        return items
