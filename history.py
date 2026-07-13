"""Persistent transcript history — saved to disk as JSON.

Stores recent transcripts with timestamps so the user can search/copy from history
across sessions.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import config

HISTORY_FILE = Path.home() / ".config" / "whisperflow" / "history.json"


def _ensure_dir():
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def load():
    """Load history from disk; return list of {text, timestamp}."""
    _ensure_dir()
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save(entries):
    """Save entries (list of dicts) to disk."""
    _ensure_dir()
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except IOError:
        pass  # silently fail


def add(text):
    """Add a new transcript to history."""
    entries = load()
    entries.insert(0, {"text": text, "timestamp": datetime.now().isoformat()})
    del entries[config.HISTORY_SIZE :]
    save(entries)
