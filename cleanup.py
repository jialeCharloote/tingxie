"""Optional transcript cleanup via a local LLM on Ollama.

Removes filler words (嗯/呃/那个/um/uh), fixes punctuation, and lightly formats
the text — without translating or rewriting. 100% local (localhost:11434).
"""

import json
import subprocess
import time
import urllib.error
import urllib.request

import config

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

    def _request(self, text, timeout):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for raw, cleaned in FEW_SHOT:
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

    def clean(self, text):
        """Return cleaned text; on any failure, fall back to the raw text."""
        if not text:
            return text
        try:
            cleaned = self._request(text, timeout=config.CLEANUP_TIMEOUT)
            # Guard against a misbehaving model: an empty or wildly longer
            # answer means something went wrong — keep the raw transcript.
            if cleaned and len(cleaned) < len(text) * 3:
                return _fix_punctuation(cleaned)
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
