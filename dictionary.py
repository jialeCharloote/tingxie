"""Personal dictionary — fix words the STT model keeps getting wrong.

Rules live in ~/.config/whisperflow/dictionary.json as {"wrong": "right"} pairs
(seeded with examples on first run). Pure-ASCII keys match whole words,
case-insensitively; keys containing CJK match as exact substrings (Chinese has
no word boundaries). Keys starting with "_" are ignored — use them for notes.

The file is re-read whenever its mtime changes, so edits apply to the next
dictation without restarting the app.
"""

import json
import re
from pathlib import Path

import config

_SEED = {
    "_readme": (
        '"wrong": "right" — ASCII keys match whole words (case-insensitive), '
        "keys with 中文 match exactly. Edits apply live, no restart needed. "
        'Keys starting with "_" are ignored.'
    ),
    "cloud code": "Claude Code",
    "克劳德": "Claude",
}

_cache = {"mtime": None, "rules": []}


def _compile(entries):
    rules = []
    for wrong, right in entries.items():
        if wrong.startswith("_") or not wrong:
            continue
        if wrong.isascii():
            # Not \b: Python counts CJK as word chars, so \b wouldn't match at
            # a zh/en seam like 用cloud code和. Only ASCII alnum blocks a match.
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(wrong)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
        else:
            pattern = re.compile(re.escape(wrong))
        rules.append((pattern, right))
    return rules


def _rules():
    path = Path(config.DICTIONARY_FILE).expanduser()
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_SEED, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        mtime = path.stat().st_mtime
        if mtime != _cache["mtime"]:
            _cache["rules"] = _compile(json.loads(path.read_text(encoding="utf-8")))
            _cache["mtime"] = mtime
    except (OSError, json.JSONDecodeError, TypeError):
        pass  # bad/missing file: keep the last good rules
    return _cache["rules"]


def apply(text):
    """Run all replacement rules over the text. Cheap and idempotent."""
    if not config.DICTIONARY_ENABLED or not text:
        return text
    for pattern, right in _rules():
        text = pattern.sub(right, text)
    return text
