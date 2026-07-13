"""Optional transcript cleanup via a local LLM on Ollama.

Removes filler words (嗯/呃/那个/um/uh), fixes punctuation, and lightly formats
the text — without translating or rewriting. 100% local (localhost:11434).
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.request

import config


def worth_cleaning(text):
    """Gate the LLM pass by utterance length: short replies aren't worth ~1s.

    Mixed zh/en length = CJK characters + ASCII word runs, so "好的 sounds good"
    counts as 4, not 2 "words".
    """
    if not config.CLEANUP_MIN_TOKENS:
        return True
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return cjk + words >= config.CLEANUP_MIN_TOKENS

SYSTEM_PROMPT = """\
你是一个语音转写文本的清理工具。只做这三件事:
1. 删除口头填充词(嗯、呃、啊、那个、就是说、um、uh、like、you know 等)
2. 修正标点和大小写
3. 其余一个字都不改:不翻译、不换词、不调语序、不总结。中文保持中文,英文保持英文,混杂保持混杂。

只输出清理后的文本。"""

# Few-shot examples: small local models follow demonstrations far better than
# rules — especially "don't translate mixed zh/en text".
FEW_SHOT = [
    (
        "嗯就是说我今天呃想用那个python写一个um voice dictation的app",
        "我今天想用Python写一个voice dictation的app。",
    ),
    (
        "so um i think like 这个feature应该呃放在下个sprint做 you know",
        "So I think 这个feature应该放在下个sprint做。",
    ),
    (
        "然后那个我们需要嗯把这个API的那个rate limit呃调高一点",
        "然后我们需要把这个API的rate limit调高一点。",
    ),
]

# Per-app tone hints, appended to the system prompt (see config.APP_TONES).
TONE_HINTS_CLEAN = {
    "casual": (
        "语境:聊天消息。哈/啦/呀/吧这类语气词不算填充词,保留它们;"
        "整体保持随手打字的轻松感,句尾不要加句号。"
    ),
    "formal": (
        "语境:正式文本(邮件/文档)。标点和大小写务必完整规范,"
        "语气词(吧/哈/啦)也算填充词、一并删除。上面的规则 3 依然"
        "完全适用:不翻译、不换词、不调语序。"
    ),
}
TONE_HINTS_TRANSLATE = {
    "casual": (
        "语境:聊天消息。译文要像随手发消息一样自然随意,"
        "可以用缩写(I'm/don't),句尾不要加句号。"
    ),
    "formal": "语境:正式邮件/文档。译文要得体、专业、完整。",
}


def _apply_tone(text, tone):
    """Deterministic finishing touches the model can't be trusted with."""
    if tone == "casual" and text[-1:] in ("。", ".") and text[-2:-1] not in ("。", "."):
        return text[:-1]  # texting style: no trailing period (keep ! ? and …)
    return text


TRANSLATE_PROMPT = """\
你是一个语音转写的翻译工具。把用户说的话翻译成地道、自然的{target}:
1. 先忽略口头填充词(嗯、呃、那个、um、uh 等),再翻译
2. 意思和语气保持原样:口语翻成地道的口语,不要变正式、不要总结
3. 原文里已经是{target}的部分自然融入译文

只输出翻译结果。"""

# Translation few-shot: casual spoken zh/en-mixed input → natural English.
FEW_SHOT_TRANSLATE = [
    (
        "嗯我觉得这个feature呃可以放到下个sprint再做",
        "I think this feature can wait until the next sprint.",
    ),
    (
        "帮我跟他说一下那个meeting改到周四了",
        "Please let him know the meeting has been moved to Thursday.",
    ),
    (
        "这个bug太诡异了我查了一下午都没有repro出来",
        "This bug is so weird — I spent the whole afternoon on it and still couldn't repro it.",
    ),
]


class Cleaner:
    def __init__(self):
        self.url = f"http://{config.OLLAMA_HOST}/api/chat"
        self._ensure_server()
        self._warm_up()

    def _ensure_server(self):
        """Start `ollama serve` if it isn't already running."""
        try:
            urllib.request.urlopen(
                f"http://{config.OLLAMA_HOST}/api/version", timeout=1
            )
            return
        except (urllib.error.URLError, OSError):
            pass
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(20):  # wait up to ~10s for it to come up
            time.sleep(0.5)
            try:
                urllib.request.urlopen(
                    f"http://{config.OLLAMA_HOST}/api/version", timeout=1
                )
                return
            except (urllib.error.URLError, OSError):
                continue
        raise RuntimeError("Could not start Ollama. Is it installed? (brew install ollama)")

    def _request(self, text, timeout, system=SYSTEM_PROMPT, few_shot=FEW_SHOT):
        messages = [{"role": "system", "content": system}]
        for raw, cleaned in few_shot:
            messages.append({"role": "user", "content": raw})
            messages.append({"role": "assistant", "content": cleaned})
        messages.append({"role": "user", "content": text})
        payload = {
            "model": config.CLEANUP_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": config.CLEANUP_KEEP_ALIVE,  # keep model warm in RAM
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["message"]["content"].strip()

    def _warm_up(self):
        """Load the model into memory so the first real request is fast."""
        try:
            self._request("你好", timeout=120)
        except Exception:
            pass  # non-fatal: first real request will just be slower

    def clean(self, text, tone=None):
        """Return cleaned text; on any failure, fall back to the raw text."""
        if not text:
            return text
        system = SYSTEM_PROMPT
        if tone in TONE_HINTS_CLEAN:
            system += "\n\n" + TONE_HINTS_CLEAN[tone]
        try:
            cleaned = self._request(text, timeout=config.CLEANUP_TIMEOUT, system=system)
            # Guard against a misbehaving model: an empty or wildly longer
            # answer means something went wrong — keep the raw transcript.
            if cleaned and len(cleaned) < len(text) * 3:
                return _apply_tone(_fix_punctuation(cleaned), tone)
        except Exception:
            pass
        return text

    def translate(self, text, tone=None):
        """Translate to config.TRANSLATE_TARGET; on failure, return the raw text.

        No length guard here: zh→en legitimately grows the character count
        several-fold, so only an empty answer counts as failure.
        """
        if not text:
            return text
        system = TRANSLATE_PROMPT.format(target=config.TRANSLATE_TARGET)
        if tone in TONE_HINTS_TRANSLATE:
            system += "\n" + TONE_HINTS_TRANSLATE[tone]
        try:
            translated = self._request(
                text,
                timeout=config.TRANSLATE_TIMEOUT,
                system=system,
                few_shot=FEW_SHOT_TRANSLATE,
            )
            if translated:
                return _apply_tone(_fix_punctuation(translated), tone)
        except Exception:
            pass
        return text


_CJK_TO_ASCII = str.maketrans({"。": ".", "，": ",", "！": "!", "？": "?",
                               "：": ":", "；": ";"})


def _fix_punctuation(text):
    """If the text contains no CJK characters, use ASCII punctuation."""
    if any("一" <= ch <= "鿿" for ch in text):
        return text
    return text.translate(_CJK_TO_ASCII)
