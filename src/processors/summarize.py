import os
import json
import requests

# 翻译模块砍除后，截断常量搬到 summarize 这里——作用于送入提示词前的 content 预处理
SHALLOW_SOURCES = {"X", "HackerNews", "Reddit"}
SHALLOW_LIMIT = 200   # 浅截断：社交类源原文本来就短

DEEP_LIMIT = 5000     # 深截断：长博客超过 5000 字损失轻、token 不爆

# GitHub 雷达本轮留空、HF 模型描述无须精摘——跳过这两个源
SKIP_SUMMARIZE_SOURCES = {"GitHub", "HuggingFace"}


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
        prompt = f"""你是一位专业的AI新闻编辑。请对以下{source}内容做深度分析，按 JSON 返回，不要包含任何其他文字。

注意：chinese_summary 与 editor_note 是两个独立字段，分工严格：
- chinese_summary：客观事实层，新闻通稿口吻
- editor_note：主观判断层，编辑视角

输出 JSON：
{{
  "chinese_title": "≤30 字中文标题",

  "chinese_summary": "130-170 字的客观摘要，2-3 句话。新闻通稿口吻，可以分点列举关键信息（'核心功能包括：A；B；C'）。包含核心事件 + 关键数字/产品名/版本号。禁止'值得关注''重磅'等评价性套话。如果原文是英文，直接消化产出中文，不要先翻译再压缩。",

  "tags": ["≤4 个","简短关键词","中英文均可","用于卡片下方展示"],

  "category": "从 [模型发布, 产品更新, 技术论文, 行业观点, 投资融资, 开源工具] 中选择最贴合的一个",

  "editor_note": "30-80 字的编辑短评，编辑视角。回答'读者为什么应该花时间看这条'——判断 / 对比 / 提醒 / 祛魅，敢负面评价。禁止重复 chinese_summary 已经讲过的事实。口语化，不要场面话。",

  "sentiment": "positive / neutral / negative"
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
                "tags": [],
                "category": "行业观点",
                "editor_note": "（按语生成失败，模型返回未通过 JSON 解析）",
                "sentiment": "neutral"
            }
        # 即使 LLM 错误返回了砍除字段，显式清掉
        data.pop("importance", None)
        data.pop("original_excerpt", None)
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
            # 按 source 截断 content，控制提示词长度
            content = item.get("content", "") or ""
            source = item.get("source", "")
            if source in SHALLOW_SOURCES and len(content) > SHALLOW_LIMIT:
                content_for_prompt = content[:SHALLOW_LIMIT]
            elif source in SKIP_SUMMARIZE_SOURCES:
                # GitHub / HuggingFace 本轮跳过摘要（GH 雷达留空、HF 模型描述无需精摘）
                continue
            elif len(content) > DEEP_LIMIT:
                content_for_prompt = content[:DEEP_LIMIT]
            else:
                content_for_prompt = content

            result = self.summarize_item(
                item.get("title", ""),
                content_for_prompt,
                item.get("source", "未知")
            )
            item.update(result)

        # 全局清场：本架构不再使用 importance / original_excerpt
        for item in items:
            item.pop("importance", None)
            item.pop("original_excerpt", None)
        return items
