"""Inject transcribed text into whatever macOS app currently has focus.

Also implements the two-stage swap: paste the raw transcript instantly, then
replace it in place once the LLM-cleaned version is ready. The swap is guarded
— it aborts if the user typed/clicked or switched apps in between, so it can
never clobber anything but our own just-pasted text.
"""

import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

import config

_keyboard = Controller()

# Pre-resolve the lazy pyobjc symbol pynput listeners touch from their worker
# threads. Starting the keyboard + mouse listeners together makes both threads
# race objc._lazyimport and one dies with KeyError: 'AXIsProcessTrusted';
# resolving it once here (single-threaded) makes later lookups plain reads.
try:
    import HIServices

    HIServices.AXIsProcessTrusted()
except Exception:
    pass

# Clipboard contents saved by a two-stage first paste, restored after the swap.
_saved_clipboard = None


def _clipboard_snapshot():
    """Snapshot the ENTIRE pasteboard — every item, every type (text, images,
    files…). pyperclip only round-trips text; restoring through it would eat
    a copied image. Returns None if the pasteboard can't be read."""
    try:
        from AppKit import NSPasteboard

        items = []
        for item in NSPasteboard.generalPasteboard().pasteboardItems() or []:
            entry = {}
            for t in item.types() or []:
                data = item.dataForType_(t)
                if data is not None:
                    entry[t] = data
            if entry:
                items.append(entry)
        return items
    except Exception:
        return None


def _clipboard_restore(snapshot):
    """Put a _clipboard_snapshot back. [] restores an empty pasteboard;
    None (snapshot failed) leaves the pasteboard alone."""
    if snapshot is None:
        return
    try:
        from AppKit import NSPasteboard, NSPasteboardItem

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        restored = []
        for entry in snapshot:
            item = NSPasteboardItem.alloc().init()
            for t, data in entry.items():
                item.setData_forType_(data, t)
            restored.append(item)
        if restored:
            pb.writeObjects_(restored)
    except Exception:
        pass


def frontmost_app():
    """Bundle id of the app that currently has focus ('' if unknown)."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() or ""
    except Exception:
        return ""


def _lookup_by_bundle(mapping, bundle_id, default):
    if bundle_id:
        for fragment, value in mapping.items():
            if fragment.lower() in bundle_id.lower():
                return value
    return default


def resolve_method(bundle_id=None):
    """Inject method for the frontmost app: per-app override or the default."""
    bundle_id = frontmost_app() if bundle_id is None else bundle_id
    return _lookup_by_bundle(config.INJECT_OVERRIDES, bundle_id, config.INJECT_METHOD)


def resolve_tone(bundle_id=None):
    """LLM tone for the frontmost app: 'casual', 'formal', or None (neutral)."""
    bundle_id = frontmost_app() if bundle_id is None else bundle_id
    return _lookup_by_bundle(config.APP_TONES, bundle_id, None)


def _paste(text, restore=True):
    """Clipboard method: save clipboard, copy text, Cmd+V, restore clipboard.

    With restore=False (two-stage first paste) the previous clipboard is kept
    in _saved_clipboard for the swap/restore step to deal with later.
    """
    global _saved_clipboard
    previous = None
    if config.RESTORE_CLIPBOARD:
        previous = _clipboard_snapshot()

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

    if not restore:
        _saved_clipboard = previous
    elif config.RESTORE_CLIPBOARD:
        _schedule_restore(previous)


def _schedule_restore(previous):
    # Electron apps (WeChat, browsers) read the clipboard asynchronously —
    # restoring too early makes the paste land the OLD clipboard content.
    # Restore late, off-thread, so dictation latency is unaffected.
    def restore():
        time.sleep(1.0)
        _clipboard_restore(previous)

    threading.Thread(target=restore, daemon=True).start()


def _type(text):
    """Direct keystroke synthesis: works in Terminal, VS Code, etc."""
    _keyboard.type(text)


def inject(text, restore=True):
    if not text:
        return
    if resolve_method() == "type":
        _type(text)
    else:
        _paste(text, restore=restore)


def retract(old_text):
    """Delete the just-injected old_text: select back over it and backspace.
    Caller is responsible for checking the cursor hasn't moved (same app,
    recent paste) — this only makes sense right after an inject."""
    time.sleep(0.1)
    _keyboard.press(Key.shift)
    try:
        for _ in range(len(old_text)):
            _keyboard.press(Key.left)
            _keyboard.release(Key.left)
            time.sleep(0.003)
    finally:
        _keyboard.release(Key.shift)
    time.sleep(0.05)
    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)


def grab_selection():
    """Copy the current selection via Cmd+C and return it ('' if none).

    Called right after the hotkey is released (voice-edit mode), so we pause
    first to let fn/option residue clear — same trick as _paste. The user's
    clipboard is put back before returning.
    """
    previous = _clipboard_snapshot()
    sentinel = "\x00whisperflow:no-selection\x00"
    pyperclip.copy(sentinel)
    time.sleep(0.25)  # modifier residue + clipboard settle

    _keyboard.press(Key.cmd)
    time.sleep(0.03)
    _keyboard.press("c")
    time.sleep(0.03)
    _keyboard.release("c")
    time.sleep(0.03)
    _keyboard.release(Key.cmd)

    text = sentinel
    for _ in range(10):  # apps write the clipboard asynchronously
        time.sleep(0.08)
        try:
            text = pyperclip.paste()
        except Exception:
            text = sentinel
        if text != sentinel:
            break
    if text == sentinel:
        text = ""  # nothing selected — Cmd+C left the clipboard untouched

    _clipboard_restore(previous)
    time.sleep(0.05)
    return text


# ── Two-stage swap ─────────────────────────────────────────────────────────────

class SwapGuard:
    """Watches for user activity between the raw paste and the cleaned swap.

    Any real key press or mouse click (our own synthetic events happen while
    this is stopped) means the cursor may have moved — swapping would clobber
    the wrong text, so the swap is abandoned.
    """

    def __init__(self):
        self.dirty = False
        self.app = frontmost_app()
        self._listeners = []
        try:
            from pynput import keyboard, mouse

            kl = keyboard.Listener(on_press=self._touch)
            ml = mouse.Listener(on_click=self._touch)
            kl.start()
            ml.start()
            self._listeners = [kl, ml]
        except Exception:
            self.dirty = True  # can't watch — never risk a blind swap

    def _touch(self, *args, **kwargs):
        self.dirty = True

    def stop(self):
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners = []

    def safe(self):
        return not self.dirty and frontmost_app() == self.app


def two_stage_ok(text):
    """Whether this take should paste raw now and swap in the polish later."""
    return (
        config.TWO_STAGE_PASTE
        and len(text) <= config.TWO_STAGE_MAX_CHARS
        and "\n" not in text
        and resolve_method() == "paste"
    )


def swap_or_keep(guard, old_text, new_text):
    """Finish a two-stage take: replace old_text with new_text if it's still
    safe to do so, then restore the clipboard saved by the first paste."""
    global _saved_clipboard
    guard.stop()
    if new_text != old_text and guard.safe():
        # Select back over exactly what we pasted, then paste the replacement.
        _keyboard.press(Key.shift)
        try:
            for _ in range(len(old_text)):
                _keyboard.press(Key.left)
                _keyboard.release(Key.left)
                time.sleep(0.003)
        finally:
            _keyboard.release(Key.shift)
        time.sleep(0.05)
        pyperclip.copy(new_text)
        time.sleep(0.15)
        _keyboard.press(Key.cmd)
        time.sleep(0.03)
        _keyboard.press("v")
        time.sleep(0.03)
        _keyboard.release("v")
        time.sleep(0.03)
        _keyboard.release(Key.cmd)
        swapped = True
    else:
        swapped = new_text == old_text  # nothing to change still counts as done
    if config.RESTORE_CLIPBOARD:
        _schedule_restore(_saved_clipboard)
    _saved_clipboard = None
    return swapped
