"""Personal dictionary — fix words the STT model keeps getting wrong.

Rules live in ~/.config/whisperflow/dictionary.json as {"wrong": "right"} pairs
(seeded with examples on first run). Pure-ASCII keys match whole words,
case-insensitively; keys containing CJK match as exact substrings (Chinese has
no word boundaries). Keys starting with "_" are ignored — use them for notes.

Two passes:
  1. exact — every rule's wrong spelling replaced with its right value.
  2. fuzzy (optional) — spans close to a key but not exactly it get corrected
     too, so you don't have to enumerate every way the model mishears a term.
     Guarded by a similarity threshold and a minimum key length; short keys are
     never fuzzed (a loose bar over 2-3 chars rewrites real words).

The file is re-read whenever its mtime changes, so edits apply to the next
dictation without restarting the app.
"""

import json
import re
from collections import namedtuple
from difflib import SequenceMatcher
from pathlib import Path

import config

_SEED = {
    "_readme": (
        '"wrong": "right" — ASCII keys match whole words (case-insensitive), '
        "keys with 中文 match exactly. Near-misses are fuzzy-matched too (keys "
        "≥4 chars). Edits apply live, no restart needed. Keys starting with "
        '"_" are ignored.'
    ),
    "cloud code": "Claude Code",
    "克劳德": "Claude",
}

# is_ascii distinguishes the two matching modes; pattern is the exact matcher;
# size is word-count (ASCII) or char-count (CJK), used to size fuzzy windows.
Rule = namedtuple("Rule", "wrong right is_ascii pattern size")

_cache = {"mtime": None, "rules": []}

_ASCII_TOKEN = re.compile(r"[A-Za-z0-9]+")


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
            size = len(_ASCII_TOKEN.findall(wrong)) or 1
            rules.append(Rule(wrong, right, True, pattern, size))
        else:
            pattern = re.compile(re.escape(wrong))
            rules.append(Rule(wrong, right, False, pattern, len(wrong)))
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


def _fuzzy_candidates(text, rule, threshold):
    """Spans in `text` that resemble rule.wrong but aren't an exact hit.
    Returns (start, end, replacement, score) tuples."""
    out = []
    if rule.is_ascii:
        key = rule.wrong.lower()
        right_l = rule.right.lower()
        toks = _ASCII_TOKEN.findall(text)
        spans = list(_ASCII_TOKEN.finditer(text))
        n = rule.size
        for i in range(len(spans) - n + 1):
            start, end = spans[i].start(), spans[i + n - 1].end()
            norm = " ".join(t.lower() for t in toks[i:i + n])
            # exact hit was already handled; leave the correct value alone
            if norm == key or norm == right_l:
                continue
            score = SequenceMatcher(None, norm, key).ratio()
            if score >= threshold:
                out.append((start, end, rule.right, score))
    else:
        key = rule.wrong
        length = rule.size
        # ±1 window absorbs an inserted or dropped character
        for w in {length - 1, length, length + 1}:
            if w < 1:
                continue
            for i in range(len(text) - w + 1):
                span = text[i:i + w]
                if span == key or span == rule.right or span.isascii():
                    continue  # exact/correct/latin-noise — skip
                score = SequenceMatcher(None, span, key).ratio()
                if score >= threshold:
                    out.append((i, i + w, rule.right, score))
    return out


def _fuzzy(text, rules):
    threshold = config.DICTIONARY_FUZZY_THRESHOLD
    min_len = config.DICTIONARY_FUZZY_MIN_LEN
    candidates = []
    for rule in rules:
        if len(rule.wrong) < min_len:
            continue
        candidates += _fuzzy_candidates(text, rule, threshold)
    if not candidates:
        return text
    # Best score wins; resolve overlaps greedily so each character is rewritten
    # at most once, then splice from the right to keep earlier indices valid.
    candidates.sort(key=lambda c: (-c[3], c[0]))
    occupied = [False] * len(text)
    chosen = []
    for start, end, right, _score in candidates:
        if any(occupied[start:end]):
            continue
        chosen.append((start, end, right))
        for k in range(start, end):
            occupied[k] = True
    for start, end, right in sorted(chosen, key=lambda c: -c[0]):
        text = text[:start] + right + text[end:]
    return text


def apply(text):
    """Run all replacement rules over the text. Cheap and idempotent."""
    if not config.DICTIONARY_ENABLED or not text:
        return text
    rules = _rules()
    for rule in rules:
        text = rule.pattern.sub(rule.right, text)
    if config.DICTIONARY_FUZZY:
        text = _fuzzy(text, rules)
    return text
