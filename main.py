"""
Local Whisper Flow clone.

Two ways to dictate (both 100% local):
  HOLD fn  — push-to-talk: speak while holding, release to transcribe + paste
  TAP fn   — hands-free: speak freely; stops when you tap fn again or when
             you go quiet for a moment (Silero VAD)

Tip: set System Settings > Keyboard > "Press 🌐 key to" = "Do Nothing" so
holding fn doesn't also trigger the emoji picker or macOS dictation.

    python main.py

Requires macOS permissions (System Settings > Privacy & Security):
  - Microphone            (to record)
  - Accessibility         (to paste / send keystrokes)
  - Input Monitoring      (to capture the global hotkey)
Grant them to your terminal app (Terminal / iTerm) the first time.
"""

import threading
import time

from rich.console import Console

import config
import dictionary
from audio import Recorder
from cleanup import Cleaner, worth_cleaning
from history import add as history_add, load as history_load
from hotkey import make_listener
from inject import SwapGuard, inject, swap_or_keep, two_stage_ok
from sounds import play
from transcribe import Transcriber
from vad import VadMonitor

console = Console()


def check_accessibility():
    """Prompt for the Accessibility permission if we don't have it.

    Without it, macOS silently drops our synthetic Cmd+V — transcription
    appears to work but nothing ever pastes. AXIsProcessTrustedWithOptions
    with the prompt flag shows the system dialog and pre-adds us to the list.
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            console.print(
                "[bold red]⚠ Accessibility permission missing — paste will NOT "
                "work.[/]\nEnable it: System Settings → Privacy & Security → "
                "Accessibility → allow Python, then restart this app."
            )
    except Exception:
        pass


class DictationApp:
    def __init__(self):
        check_accessibility()
        console.print(f"[bold cyan]Loading STT model…[/] ({config.STT_BACKEND})")
        self.transcriber = Transcriber()
        self.cleaner = None
        if config.CLEANUP_ENABLED or config.TRANSLATE_ENABLED:
            console.print(f"[bold cyan]Warming up cleanup LLM…[/] ({config.CLEANUP_MODEL})")
            self.cleaner = Cleaner()
        self.recorder = Recorder()
        self._recording = False
        self._handsfree = False
        self._translate = False
        self._fn_down_at = 0.0
        self._vad = None
        self._lock = threading.Lock()
        self.on_state = lambda state: None  # UI hook: idle/recording/processing
        self.on_history = lambda text: None  # UI hook: a transcript was pasted
        self.history = []  # last few pasted transcripts (newest first)
        translate_hint = (
            f" · shift+{config.HOTKEY} = → {config.TRANSLATE_TARGET}"
            if config.TRANSLATE_ENABLED and self.cleaner is not None
            else ""
        )
        console.print("[bold green]Ready.[/] "
                      f"Hold [bold]{config.HOTKEY}[/] = push-to-talk · "
                      f"tap = hands-free{translate_hint} · esc = cancel. "
                      "Ctrl+C to quit.")

    # ── fn key state machine ──────────────────────────────────────────────
    def on_fn_down(self, shift=False):
        self._fn_down_at = time.monotonic()
        with self._lock:
            if self._recording:
                return  # hands-free session in progress; the UP ends it
            self._recording = True
        self._translate = (
            shift and config.TRANSLATE_ENABLED and self.cleaner is not None
        )
        if self._translate:
            console.print(f"[yellow]● recording… (→ {config.TRANSLATE_TARGET})[/]")
        else:
            console.print("[yellow]● recording…[/]")
        self.on_state("translating" if self._translate else "recording")
        play("start")
        self._vad = None
        if config.VAD_ENABLED:
            self._vad = VadMonitor(on_silence=self._on_vad_silence)
        self.recorder.start(on_chunk=self._vad.feed if self._vad else None)

    def on_fn_up(self):
        held = time.monotonic() - self._fn_down_at
        if self._handsfree:
            # Any tap while hands-free ends the take.
            self._handsfree = False
            self.stop_and_process()
        elif held < config.TAP_THRESHOLD:
            self._handsfree = True
            console.print("[yellow]  hands-free — tap fn or pause to finish[/]")
        else:
            self.stop_and_process()

    def on_fn_double_tap(self):
        # Quick-toggle AI cleanup via double-tap
        if self.cleaner is not None:
            config.CLEANUP_ENABLED = not config.CLEANUP_ENABLED
            state = "[green]ON[/]" if config.CLEANUP_ENABLED else "[dim]OFF[/]"
            console.print(f"AI Cleanup: {state}")

    def on_esc(self):
        # Esc while recording: throw the take away — nothing gets pasted.
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        self._handsfree = False
        if self._vad is not None:
            self._vad.close()
            self._vad = None
        self.recorder.stop()  # discard the audio
        play("cancel")
        console.print("[dim](cancelled — nothing pasted)[/]")
        self.on_state("idle")

    def on_shift_change(self, pressed):
        # Pressing shift at ANY point while recording toggles translate mode —
        # so shift-before-fn vs fn-before-shift ordering doesn't matter.
        if not pressed or not self._recording:
            return
        if not (config.TRANSLATE_ENABLED and self.cleaner is not None):
            return
        self._translate = not self._translate
        if self._translate:
            console.print(f"[yellow]  → {config.TRANSLATE_TARGET} mode[/]")
            self.on_state("translating")
        else:
            console.print("[yellow]  → normal dictation[/]")
            self.on_state("recording")

    def _on_vad_silence(self):
        # Fires from the VAD thread after sustained silence in hands-free mode.
        if self._handsfree:
            self._handsfree = False
            console.print("[dim](silence detected)[/]")
            self.stop_and_process()

    def stop_and_process(self):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        if self._vad is not None:
            self._vad.close()
            self._vad = None
        audio = self.recorder.stop()
        play("stop")
        self.on_state("processing")
        console.print("[cyan]… transcribing[/]")
        try:
            text = self.transcriber.transcribe(audio)
            if not text:
                console.print("[dim](no speech detected)[/]")
                return
            text = dictionary.apply(text)
            console.print(f"[dim]raw:[/] {text}")
            injected = False
            if self._translate:
                text = dictionary.apply(self.cleaner.translate(text))
                console.print(f"[bold white]⇢ {text}[/]")
            elif self.cleaner is not None and config.CLEANUP_ENABLED:
                if not worth_cleaning(text):
                    console.print("[dim](short utterance — cleanup skipped)[/]")
                elif two_stage_ok(text):
                    # paste raw now, swap in the polished version when ready
                    inject(text, restore=False)
                    injected = True
                    guard = SwapGuard()
                    cleaned = dictionary.apply(self.cleaner.clean(text))
                    if swap_or_keep(guard, text, cleaned):
                        text = cleaned
                        console.print(f"[bold white]→ {text}[/]")
                    else:
                        console.print("[dim](you moved on — kept the raw paste)[/]")
                else:
                    # re-apply the dictionary in case the LLM re-broke a term
                    text = dictionary.apply(self.cleaner.clean(text))
                    console.print(f"[bold white]→ {text}[/]")
            if not injected:
                inject(text)
            history_add(text)  # persist to disk
            self.history.insert(0, text)
            del self.history[config.HISTORY_SIZE:]
            self.on_history(text)
        finally:
            self.on_state("idle")

    def run(self):
        listener = make_listener(
            config.HOTKEY,
            on_press=self.on_fn_down,
            on_release=self.on_fn_up,
            on_double_tap=self.on_fn_double_tap,
            on_shift=self.on_shift_change,
            on_esc=self.on_esc,
        )
        if config.MENU_BAR:
            self._run_with_menu_bar(listener)
        else:
            listener.run()

    def _run_with_menu_bar(self, listener):
        """Menu bar icon on the main thread, hotkey listener on a worker."""
        import pyperclip
        import rumps
        from PyObjCTools import AppHelper

        overlay = None
        if config.OVERLAY_ENABLED:
            from overlay import Overlay

            overlay = Overlay()

        icons = {"idle": "🎙", "recording": "🔴", "translating": "🌐", "processing": "⏳"}
        app = rumps.App("whisper-flow", title=icons["idle"], quit_button="Quit")

        # ── menu: AI cleanup toggle ────────────────────────────────────────
        cleanup_enabled = [config.CLEANUP_ENABLED and self.cleaner is not None]

        def toggle_cleanup(item):
            cleanup_enabled[0] = not cleanup_enabled[0]
            config.CLEANUP_ENABLED = cleanup_enabled[0]
            item.state = cleanup_enabled[0]
            console.print(
                f"AI Cleanup: {'[green]ON[/]' if cleanup_enabled[0] else '[dim]OFF[/]'}"
            )

        cleanup_item = rumps.MenuItem("AI Cleanup (qwen2.5)", callback=toggle_cleanup)
        cleanup_item.state = cleanup_enabled[0]
        if self.cleaner is None:
            cleanup_item.set_callback(None)  # Ollama unavailable — grey out

        # ── menu: recent transcripts, click to copy ────────────────────────
        history_menu = rumps.MenuItem("History")

        # Load persisted history from disk
        disk_history = history_load()
        if disk_history:
            for entry in disk_history:
                text = entry.get("text", "")
                title = text if len(text) <= 40 else text[:39] + "…"
                history_menu.add(
                    rumps.MenuItem(title, callback=lambda _, t=text: pyperclip.copy(t))
                )
        else:
            history_menu.add(rumps.MenuItem("(empty)"))

        def rebuild_history(_text):
            def do():
                history_menu.clear()
                if self.history:
                    for entry in self.history:
                        title = entry if len(entry) <= 40 else entry[:39] + "…"
                        history_menu.add(
                            rumps.MenuItem(title, callback=lambda _, t=entry: pyperclip.copy(t))
                        )
                else:
                    history_menu.add(rumps.MenuItem("(empty)"))

            AppHelper.callAfter(do)

        self.on_history = rebuild_history
        app.menu = [cleanup_item, history_menu, None]  # None = separator

        # ── state → icon + overlay (dispatched to the main thread) ─────────
        def set_state(state):
            AppHelper.callAfter(setattr, app, "title", icons[state])
            if overlay is not None:
                if state == "recording":
                    overlay.recording()
                elif state == "translating":
                    overlay.recording(f"→ {config.TRANSLATE_TARGET}…")
                elif state == "processing":
                    overlay.processing()
                else:
                    overlay.hide()

        self.on_state = set_state

        threading.Thread(target=listener.run, daemon=True).start()
        app.run()


if __name__ == "__main__":
    try:
        DictationApp().run()
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/]")
