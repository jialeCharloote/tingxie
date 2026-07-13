"""Daily usage stats — takes and characters, persisted as JSON."""

import json
from datetime import date
from pathlib import Path

import config

# vs hand-typing mixed zh/en at roughly this many chars per minute
_TYPING_CPM = 80


def _path():
    return Path(config.STATS_FILE).expanduser()


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record(chars):
    if not config.STATS_ENABLED:
        return
    try:
        data = _load()
        day = data.setdefault(date.today().isoformat(), {"takes": 0, "chars": 0})
        day["takes"] += 1
        day["chars"] += chars
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # stats are never worth breaking a dictation over


def summary():
    """(today_dict, total_takes, total_chars, saved_minutes)"""
    data = _load()
    today = data.get(date.today().isoformat(), {"takes": 0, "chars": 0})
    total_takes = sum(d.get("takes", 0) for d in data.values())
    total_chars = sum(d.get("chars", 0) for d in data.values())
    return today, total_takes, total_chars, total_chars / _TYPING_CPM
