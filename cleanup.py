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


def pick_target(text):
    """Bidirectional translate: with the default English target, speaking
    mostly-Latin speech flips the target to TRANSLATE_TARGET_ALT (中文) —
    so one hotkey covers both directions. Non-English targets never flip."""
    if config.TRANSLATE_TARGET == "English":
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        words = len(re.findall(r"[A-Za-z]+", text))
        if words > cjk:
            return config.TRANSLATE_TARGET_ALT
    return config.TRANSLATE_TARGET


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


EDIT_PROMPT = """\
你是一个文本编辑工具。用户给你一段文本和一条口头指令,按指令修改文本:
- 只做指令要求的修改,其余尽量保持原样
- 输出语言按指令要求;指令没提语言就保持原文语言
- 只输出修改后的文本:不解释、不加引号、不加前后缀"""

FEW_SHOT_EDIT = [
    (
        "指令:改得礼貌一点\n\n文本:\n把报告发我",
        "麻烦你有空的时候把报告发我一下,谢谢!",
    ),
    (
        "指令:translate to English\n\n文本:\n我们下周三下午两点开会,记得带上roadmap",
        "We'll meet next Wednesday at 2pm — remember to bring the roadmap.",
    ),
    (
        "指令:精简一半\n\n文本:\n"
        "我个人觉得这个方案整体上来说还是可行的,虽然细节上还有一些需要再打磨的地方",
        "我觉得方案可行,细节还需打磨。",
    ),
]


STYLE_PROMPT = """\
下面是一位用户的语音听写记录(每行 [应用/模式] 文本)。总结这位用户的
语言风格,给另一个"转写润色工具"当参考,让它润色时不要抹平用户的个人
习惯。只输出 4-6 条要点,每条一行、以 "- " 开头,聚焦:
- 语气词习惯(哈/啦/吧/呀 哪些常用、要保留)
- 标点习惯(爱不爱用感叹号/省略号/句号)
- 中英混用模式(哪些概念习惯说英文)
- 整体语气(简短直接?委婉?)
只描述风格,不要评价、不要建议用户改变。"""


def load_style():
    """Current style profile text ('' if absent/disabled). Mtime-cached."""
    if not config.STYLE_ADAPT:
        return ""
    from pathlib import Path

    path = Path(config.STYLE_FILE).expanduser()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    if _style_cache["mtime"] != mtime:
        try:
            text = path.read_text(encoding="utf-8")
            # drop the metadata comment line, keep the bullets
            _style_cache["text"] = "\n".join(
                l for l in text.splitlines() if l.startswith("- ")
            )
            _style_cache["mtime"] = mtime
        except OSError:
            return _style_cache["text"]
    return _style_cache["text"]


_style_cache = {"mtime": None, "text": ""}


def _with_style(system):
    style = load_style()
    if style:
        system += (
            "\n\n补充规则(优先级最高):以下是这位用户的说话风格,"
            "润色时必须尊重、不要抹平:\n" + style +
            "\n尤其注意:风格里说要保留的语气词一律原样保留,它们不算填充词。"
        )
    return system


def _style_few_shot():
    """When the profile says the user keeps tone particles, demonstrate it —
    small models follow an example far better than a rule."""
    style = load_style()
    if any(p in style for p in "哈啦吧呀嘛哦"):
        return [(
            "嗯那个这个没问题哈我呃明天发你啦",
            "这个没问题哈,我明天发你啦",
        )]
    return []


ANALYZE_PROMPT = """\
你是一个语音输入习惯分析助手。下面是用户最近的听写记录(每行格式为
[应用/模式] 文本;完全在本机处理,仅供用户自己参考)。用中文输出一份
简洁的 markdown 分析,包含这几节:

### 口头禅与高频表达
最常出现的词和短语(中英都算),附出现语境的例子

### 中英混用习惯
怎么混、什么话题偏英文、什么场景偏中文

### 常聊的主题
从内容归纳 3-5 个主题

### 个人词典建议
反复出现、语音识别容易写错的专有名词(人名/产品名/术语),
列成 `"错的写法": "正确写法"` 的 JSON 行,方便直接粘进词典文件

### 一个有趣的观察

要具体、引用原文;不要空泛的套话。"""


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
        system = _with_style(system)
        try:
            cleaned = self._request(
                text, timeout=config.CLEANUP_TIMEOUT, system=system,
                few_shot=FEW_SHOT + _style_few_shot(),
            )
            # Guard against a misbehaving model: an empty or wildly longer
            # answer means something went wrong — keep the raw transcript.
            if cleaned and len(cleaned) < len(text) * 3:
                return _apply_tone(_fix_punctuation(cleaned), tone)
        except Exception:
            pass
        return text

    def translate(self, text, tone=None, target=None):
        """Translate to `target` (default TRANSLATE_TARGET); on failure,
        return the raw text.

        No length guard here: zh→en legitimately grows the character count
        several-fold, so only an empty answer counts as failure.
        """
        if not text:
            return text
        system = TRANSLATE_PROMPT.format(target=target or config.TRANSLATE_TARGET)
        if tone in TONE_HINTS_TRANSLATE:
            system += "\n" + TONE_HINTS_TRANSLATE[tone]
        system = _with_style(system)
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

    def edit(self, instruction, text):
        """Apply a spoken instruction to a piece of text (voice-edit mode).
        On any failure the original text comes back — pasting it over the
        still-selected source is a harmless no-op."""
        if not instruction or not text:
            return text
        try:
            edited = self._request(
                f"指令:{instruction}\n\n文本:\n{text}",
                timeout=config.EDIT_TIMEOUT,
                system=EDIT_PROMPT,
                few_shot=FEW_SHOT_EDIT,
            )
            if edited:
                return edited
        except Exception:
            pass
        return text


    def analyze(self, corpus):
        """Habit analysis over the dictation corpus (usage report)."""
        try:
            return self._request(
                corpus, timeout=config.ANALYZE_TIMEOUT,
                system=ANALYZE_PROMPT, few_shot=[],
            )
        except Exception:
            return "(分析失败 — Ollama 未响应,稍后再试)"

    def style_profile(self, corpus):
        """Distill the user's speaking style into a few bullets ('' on failure)."""
        try:
            out = self._request(
                corpus, timeout=config.ANALYZE_TIMEOUT,
                system=STYLE_PROMPT, few_shot=[],
            )
            bullets = [l for l in out.splitlines() if l.startswith("- ")]
            return "\n".join(bullets)
        except Exception:
            return ""


_CJK_TO_ASCII = str.maketrans({"。": ".", "，": ",", "！": "!", "？": "?",
                               "：": ":", "；": ";"})


def _fix_punctuation(text):
    """If the text contains no CJK characters, use ASCII punctuation."""
    if any("一" <= ch <= "鿿" for ch in text):
        return text
    return text.translate(_CJK_TO_ASCII)
