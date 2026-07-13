"""Inject transcribed text into whatever macOS app currently has focus."""

import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

import config

_keyboard = Controller()


def _paste(text):
    """Clipboard method: save clipboard, copy text, Cmd+V, restore clipboard."""
    previous = None
    if config.RESTORE_CLIPBOARD:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

    # Let the fn modifier from the just-released hotkey clear out of the event
    # stream — otherwise our Cmd+V can arrive as Cmd+fn+V, which some apps drop.
    time.sleep(0.15)

    pyperclip.copy(text)
    time.sleep(0.15)  # give the clipboard a moment to settle

    _keyboard.press(Key.cmd)
    time.sleep(0.03)
    _keyboard.press("v")
    time.sleep(0.03)
    _keyboard.release("v")
    time.sleep(0.03)
    _keyboard.release(Key.cmd)

    if config.RESTORE_CLIPBOARD:
        # Electron apps (WeChat, browsers) read the clipboard asynchronously —
        # restoring too early makes the paste land the OLD clipboard content.
        # Restore late, off-thread, so dictation latency is unaffected.
        def restore():
            time.sleep(1.0)
            try:
                pyperclip.copy(previous if previous is not None else "")
            except Exception:
                pass

        threading.Thread(target=restore, daemon=True).start()


def _type(text):
    """Direct keystroke synthesis: works in Terminal, VS Code, etc."""
    _keyboard.type(text)


def inject(text):
    if not text:
        return
    if config.INJECT_METHOD == "type":
        _type(text)
    else:
        _paste(text)
