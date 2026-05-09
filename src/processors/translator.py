"""
文章全文翻译模块
对抓取到的英文正文进行批量翻译，支持长文分段。
结果写入 item["chinese_content"]。

翻译分级（按 source 区分深度）：
- DEEP：厂商博客/个人 blog/政策/中文媒体——全文翻译（深度内容值得读完）
- SHALLOW：HN/Reddit/X——只翻译前 SHALLOW_LIMIT 字（讨论类，原文链接为主）
- 不翻译：GitHub（README 已由专属 prompt 生成中文）/ HuggingFace（模型描述无须翻）
"""
import os
import re
import requests

# 用于在送给 LLM 翻译之前 mask 掉图片 URL，避免 LLM 把 URL 弄丢或乱改
_IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# 兼容 LLM 把英文括号改成中文括号的情况
_IMG_PLACEHOLDER_RE = re.compile(r"[\(（]__IMGURL_(\d+)__[\)）]")

# 翻译分级：浅翻译（讨论类，只翻前 200 字）
SHALLOW_SOURCES = {"X", "HackerNews", "Reddit"}
SHALLOW_LIMIT = 200  # 字符上限（英文 ~50 词，中文摘要够看大意）

# 深度翻译也加上限：避免学术综述类长文（Lilian Weng / Chip Huyen 动辄 30k-50k 字）
# token 爆炸。5000 字（英文）≈ 800-1000 词，正文核心观点已经讲完；
# editor_note 给 80 字编辑解读，读者真要读全会去原文。
DEEP_LIMIT = 5000

# 翻译跳过：仓库类内容
SKIP_TRANSLATION_SOURCES = {"GitHub", "HuggingFace"}


class Translator:
    def __init__(self, config: dict):
        self.cfg = config.get("deepseek", {})
        self.api_key = os.getenv("DEEPSEEK_API_KEY", self.cfg.get("api_key", ""))
        self.api_base = self.cfg.get("api_base", "https://api.deepseek.com/v1")
        self.model = self.cfg.get("model", "deepseek-chat")
        # 每段最大英文字符数（留足 prompt + output 的 token 余量）
        self.max_chunk_len = 6000

    def _call(self, messages: list, temperature: float = 0.3) -> str:
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

    def _is_mostly_chinese(self, text: str) -> bool:
        """简单检测文本是否以中文为主（>30% 中文字符）"""
        if not text:
            return False
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        return chinese_chars / len(text) > 0.30

    def _split_into_chunks(self, text: str) -> list[str]:
        """按段落切分，每段不超过 max_chunk_len 字符"""
        if len(text) <= self.max_chunk_len:
            return [text]

        paragraphs = text.split("\n\n")
        chunks = []
        current = []
        current_len = 0

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            p_len = len(p)
            # 如果单段就超了，直接按句子切（兜底）
            if p_len > self.max_chunk_len:
                if current:
                    chunks.append("\n\n".join(current))
                    current = []
                    current_len = 0
                # 按句子切分这个超长段落
                sentences = p.replace(". ", ".\n").replace("? ", "?\n").replace("! ", "!\n").split("\n")
                sub_current = []
                sub_len = 0
                for s in sentences:
                    s = s.strip()
                    if not s:
                        continue
                    s_len = len(s)
                    if sub_len + s_len + 1 > self.max_chunk_len and sub_current:
                        chunks.append(" ".join(sub_current))
                        sub_current = [s]
                        sub_len = s_len
                    else:
                        sub_current.append(s)
                        sub_len += s_len + 1
                if sub_current:
                    chunks.append(" ".join(sub_current))
                continue

            if current_len + p_len + 2 > self.max_chunk_len and current:
                chunks.append("\n\n".join(current))
                current = [p]
                current_len = p_len
            else:
                current.append(p)
                current_len += p_len + 2

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def _mask_image_urls(self, text: str) -> tuple[str, list[str]]:
        """
        把 ![alt](url) 里的 url 替换成 __IMGURL_N__ 占位符，alt 保留让 LLM 翻译。
        返回（替换后文本, 原 url 列表）。
        """
        urls: list[str] = []

        def _sub(m: re.Match) -> str:
            alt = m.group(1)
            url = m.group(2)
            urls.append(url)
            return f"![{alt}](__IMGURL_{len(urls) - 1}__)"

        return _IMG_MD_RE.sub(_sub, text), urls

    def _restore_image_urls(self, text: str, urls: list[str]) -> str:
        """把翻译后的文本里的 __IMGURL_N__ 占位符还原成原始 URL"""
        if not urls:
            return text

        def _sub(m: re.Match) -> str:
            idx = int(m.group(1))
            if 0 <= idx < len(urls):
                return f"({urls[idx]})"
            return m.group(0)

        return _IMG_PLACEHOLDER_RE.sub(_sub, text)

    def _translate_chunk(self, text: str) -> str | None:
        """翻译单段文本"""
        # 1. mask 图片 URL，避免 LLM 把 URL 弄丢
        masked_text, urls = self._mask_image_urls(text)

        prompt = (
            "你是一位资深科技媒体编辑。请将以下英文 AI 新闻段落翻译成自然流畅的中文。\n\n"
            "要求：\n"
            "1. 保持原文的段落结构\n"
            "2. AI 专业术语首次出现时保留英文并加括号注释，如 transformer（变换器架构）、LLM（大语言模型）\n"
            "3. 代码、版本号、人名、公司名、产品名、模型名不翻译\n"
            "4. 语气正式但不生硬，适合科技新闻阅读\n"
            "5. 不要输出任何解释、总结、元数据或 Markdown 代码块标记，只输出翻译后的纯中文正文\n"
            "6. 重要：原文中所有 `__IMGURL_数字__` 是图片 URL 占位符，必须原样保留（包括外层的英文括号），"
            "不要翻译、不要修改、不要删除、也不要增加。Markdown 图片语法 `![说明](占位符)` 的整体结构必须保留。\n\n"
            f"原文：\n{masked_text}"
        )
        try:
            result = self._call([{"role": "user", "content": prompt}], temperature=0.3)
            result = result.strip()
            # 去除可能的 markdown 代码块包裹
            if result.startswith("```"):
                result = result.strip("`").strip()
                if result.lower().startswith("json"):
                    result = result[4:].strip()
                if result.lower().startswith("text"):
                    result = result[4:].strip()
                result = result.strip("`").strip()
            # 2. 还原图片 URL 占位符
            result = self._restore_image_urls(result, urls)
            return result
        except Exception as e:
            print(f"    [Translator] chunk failed: {e}")
            return None

    def translate(self, text: str) -> str | None:
        """
        翻译长文。如果文本过长则自动分段，逐段翻译后合并。
        返回中文全文；失败返回 None。
        """
        if not text or len(text.strip()) < 40:
            return None

        if self._is_mostly_chinese(text):
            return None

        chunks = self._split_into_chunks(text)
        translated = []
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            if total > 1:
                print(f"    [Translator] chunk {i + 1}/{total} ({len(chunk)} chars)...")
            t = self._translate_chunk(chunk)
            if t is None:
                return None  # 任意一段失败则整体失败，回退到原文
            translated.append(t)

        return "\n\n".join(translated)

    def process_batch(self, items: list) -> list:
        """
        批量翻译 items 列表。
        只翻译满足条件的 item：有 content、无 chinese_content、英文为主、内容足够长。
        结果写入 item["chinese_content"]。
        """
        to_translate = []
        for item in items:
            source = item.get("source", "")
            # 仓库类源跳过翻译（README 由 summarizer 直接生成中文，HF 模型描述无须翻）
            if source in SKIP_TRANSLATION_SOURCES:
                continue
            content = item.get("content", "") or ""
            if len(content.strip()) < 80:
                continue
            if item.get("chinese_content"):
                continue
            if self._is_mostly_chinese(content):
                # 原文已是中文，直接复用，避免前端无中文内容时显示异常
                item["chinese_content"] = content
                continue
            # 浅翻译源：截断到 SHALLOW_LIMIT（200 字）
            # 深度源也加 DEEP_LIMIT（5000 字）兜底，避免学术长文 token 爆炸
            if source in SHALLOW_SOURCES and len(content) > SHALLOW_LIMIT:
                item["_translation_content"] = content[:SHALLOW_LIMIT]
            elif len(content) > DEEP_LIMIT:
                item["_translation_content"] = content[:DEEP_LIMIT]
            else:
                item["_translation_content"] = content
            to_translate.append(item)

        if not to_translate:
            print("[Translator] 0 items need translation.")
            return items

        print(f"[Translator] Translating {len(to_translate)} items...")
        success = 0
        fail = 0

        for item in to_translate:
            title = item.get("chinese_title") or item.get("title", "")[:40]
            source = item.get("source", "?")
            depth = "shallow" if source in SHALLOW_SOURCES else "deep"
            text_to_translate = item.pop("_translation_content", item.get("content", ""))
            print(f"  -> [{source}|{depth}|{len(text_to_translate)}c] {title}...")
            result = self.translate(text_to_translate)
            if result:
                item["chinese_content"] = result
                success += 1
            else:
                fail += 1

        print(f"[Translator] done: success={success}, fail={fail}")
        return items
