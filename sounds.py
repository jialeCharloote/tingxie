"""Subtle audio cues using built-in macOS system sounds (fire-and-forget)."""

import subprocess

import config

_SOUNDS = {
    "start": "/System/Library/Sounds/Pop.aiff",
    "stop": "/System/Library/Sounds/Tink.aiff",
    "error": "/System/Library/Sounds/Basso.aiff",
}


def play(name):
    if not config.SOUNDS_ENABLED:
        return
    path = _SOUNDS.get(name)
    if path:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
