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
import stats
from audio import Recorder
from cleanup import Cleaner, pick_target, worth_cleaning
from history import add as history_add, load as history_load
from hotkey import make_listener
from inject import (SwapGuard, frontmost_app, grab_selection, inject,
                    resolve_tone, retract, swap_or_keep, two_stage_ok)
from preview import Preview
from sounds import play
from transcribe import Transcriber
from vad import VadMonitor

console = Console()

_STATE_FOR_MODE = {"translate": "translating", "edit": "editing", "note": "noting"}


def _append_note(text):
    from datetime import datetime
    from pathlib import Path

    path = Path(config.NOTES_FILE).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n")


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
        self._mode = None  # None | "translate" | "edit" | "note"
        self._fn_down_at = 0.0
        self._vad = None
        self._preview = None
        self._last_esc = 0.0
        self._last_paste = None  # (text, monotonic time, bundle id) for retract
        self._lock = threading.Lock()
        # Serializes take-processing (and retract): pastes land in the order
        # you spoke, and stats/history files never get concurrent writes.
        self._process_lock = threading.Lock()
        self.on_state = lambda state: None  # UI hook: idle/recording/processing/…
        self.on_history = lambda text: None  # UI hook: a transcript was pasted
        self.on_preview = lambda text: None  # UI hook: live rolling transcript
        self.history = []  # last few pasted transcripts (newest first)
        hints = [f"hold [bold]{config.HOTKEY}[/] = dictate", "tap = hands-free"]
        if config.TRANSLATE_ENABLED and self.cleaner is not None:
            hints.append(f"+shift = → {config.TRANSLATE_TARGET}")
        if config.EDIT_ENABLED and self.cleaner is not None:
            hints.append("+option = edit selection")
        if config.NOTES_ENABLED:
            hints.append("+ctrl = note")
        hints.append("esc = cancel · esc×2 = retract")
        console.print(f"[bold green]Ready.[/] {' · '.join(hints)}. Ctrl+C to quit.")

    # ── fn key state machine ──────────────────────────────────────────────
    def on_fn_down(self, shift=False, option=False, ctrl=False):
        self._fn_down_at = time.monotonic()
        with self._lock:
            if self._recording:
                return  # hands-free session in progress; the UP ends it
            self._recording = True
        llm_ready = self.cleaner is not None
        if option and config.EDIT_ENABLED and llm_ready:
            self._mode = "edit"
            console.print("[yellow]● recording… (✎ edit instruction)[/]")
        elif ctrl and config.NOTES_ENABLED:
            self._mode = "note"
            console.print("[yellow]● recording… (📝 note)[/]")
        elif shift and config.TRANSLATE_ENABLED and llm_ready:
            self._mode = "translate"
            console.print(f"[yellow]● recording… (→ {config.TRANSLATE_TARGET})[/]")
        else:
            self._mode = None
            console.print("[yellow]● recording…[/]")
        self.on_state(_STATE_FOR_MODE.get(self._mode, "recording"))
        play("start")
        self._vad = None
        if config.VAD_ENABLED:
            self._vad = VadMonitor(on_silence=self._on_vad_silence)
        self.recorder.start(on_chunk=self._vad.feed if self._vad else None)
        if config.PREVIEW_ENABLED:
            self._preview = Preview(
                self.recorder, self.transcriber, self._on_preview_text
            )

    def _on_preview_text(self, text):
        prefix = {"translate": "⇢ ", "edit": "✎ ", "note": "📝 "}.get(self._mode, "")
        self.on_preview(prefix + text)

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
        # Double-Esc while idle: retract the last dictation from the document.
        with self._lock:
            cancelling = self._recording
            self._recording = False
        if not cancelling:
            now = time.monotonic()
            if now - self._last_esc < 0.4:
                self._last_esc = 0.0
                # keystroke synthesis is slow — never block the event tap
                threading.Thread(target=self._retract_last, daemon=True).start()
            else:
                self._last_esc = now
            return
        self._handsfree = False
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.request_stop()
        if self._vad is not None:
            self._vad.close()
            self._vad = None
        self.recorder.stop()  # discard the audio
        play("cancel")
        console.print("[dim](cancelled — nothing pasted)[/]")
        self.on_state("idle")

    def _retract_last(self):
        if self._recording:
            return  # never synthesize keystrokes into an active take
        with self._process_lock:  # nor while a paste is in flight
            if self._last_paste is None:
                return
            text, when, bundle = self._last_paste
            if time.monotonic() - when > config.RETRACT_WINDOW:
                console.print("[dim](last dictation is too old to retract)[/]")
                return
            if frontmost_app() != bundle:
                console.print("[dim](different app in front — retract skipped)[/]")
                return
            self._last_paste = None
            retract(text)
            play("cancel")
            shown = text if len(text) <= 40 else text[:39] + "…"
            console.print(f"[dim](retracted: {shown})[/]")

    def on_shift_change(self, pressed):
        # Pressing shift at ANY point while recording toggles translate mode —
        # so shift-before-fn vs fn-before-shift ordering doesn't matter.
        if not pressed or not self._recording:
            return
        if self._mode not in (None, "translate"):
            return  # edit/note modes own this take
        if not (config.TRANSLATE_ENABLED and self.cleaner is not None):
            return
        if self._mode is None:
            self._mode = "translate"
            console.print(f"[yellow]  → {config.TRANSLATE_TARGET} mode[/]")
            self.on_state("translating")
        else:
            self._mode = None
            console.print("[yellow]  → normal dictation[/]")
            self.on_state("recording")

    def _on_vad_silence(self):
        # Fires from the VAD thread after sustained silence in hands-free mode.
        if self._handsfree:
            self._handsfree = False
            console.print("[dim](silence detected)[/]")
            self.stop_and_process()

    def stop_and_process(self):
        """End the take and process it. The heavy work (STT + LLM + inject)
        runs on a worker thread: this is called from the event-tap callback,
        and a slow callback gets the tap disabled by macOS — fn presses would
        silently stop arriving (the 'tap didn't end the take' bug)."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.request_stop()  # no join here — that can take ~a decode
        if self._vad is not None:
            self._vad.close()
            self._vad = None
        audio = self.recorder.stop()
        play("stop")
        self.on_state("processing")
        console.print("[cyan]… transcribing[/]")
        threading.Thread(
            target=self._process, args=(audio, self._mode, preview), daemon=True
        ).start()

    def _process(self, audio, mode, preview):
        try:
            if preview is not None:
                preview.join()  # its in-flight decode finishes first
            self._process_take(audio, mode)
        finally:
            # Don't stomp the state if the user already started a new take.
            if not self._recording:
                self.on_state("idle")

    def _process_take(self, audio, mode):
        with self._process_lock:
            text = self.transcriber.transcribe(audio)
            if not text:
                console.print("[dim](no speech detected)[/]")
                return
            text = dictionary.apply(text)
            bundle = frontmost_app()
            tone = resolve_tone(bundle)  # casual/formal/None per app
            tone_tag = f" ({tone})" if tone else ""
            console.print(f"[dim]raw{tone_tag}:[/] {text}")
            injected = False
            if mode == "edit":
                selection = grab_selection()
                if not selection:
                    play("error")
                    console.print("[red](no text selected — nothing to edit)[/]")
                    return
                text = self.cleaner.edit(text, selection)
                console.print(f"[bold white]✎ {text}[/]")
                inject(text)  # replaces the still-active selection
                injected = True
                self._last_paste = None  # retracting an edit would lose the original
            elif mode == "note":
                if (self.cleaner is not None and config.CLEANUP_ENABLED
                        and worth_cleaning(text)):
                    text = dictionary.apply(self.cleaner.clean(text))
                _append_note(text)
                injected = True  # nothing to paste — it went to the notes file
                console.print(f"[bold white]📝 → {config.NOTES_FILE}[/]")
            elif mode == "translate":
                target = pick_target(text)
                text = dictionary.apply(self.cleaner.translate(text, tone, target))
                console.print(f"[bold white]⇢ {text}[/]")
            elif self.cleaner is not None and config.CLEANUP_ENABLED:
                if not worth_cleaning(text):
                    console.print("[dim](short utterance — cleanup skipped)[/]")
                elif two_stage_ok(text):
                    # paste raw now, swap in the polished version when ready
                    inject(text, restore=False)
                    injected = True
                    guard = SwapGuard()
                    cleaned = dictionary.apply(self.cleaner.clean(text, tone))
                    if swap_or_keep(guard, text, cleaned):
                        text = cleaned
                        console.print(f"[bold white]→ {text}[/]")
                    else:
                        console.print("[dim](you moved on — kept the raw paste)[/]")
                    self._last_paste = (text, time.monotonic(), guard.app)
                else:
                    # re-apply the dictionary in case the LLM re-broke a term
                    text = dictionary.apply(self.cleaner.clean(text, tone))
                    console.print(f"[bold white]→ {text}[/]")
            if not injected:
                inject(text)
                self._last_paste = (text, time.monotonic(), bundle)
            stats.record(text, mode, bundle)
            stats.maybe_refresh_profile(
                self.cleaner,
                lambda fn: threading.Thread(target=fn, daemon=True).start(),
            )
            history_add(text)  # persist to disk
            self.history.insert(0, text)
            del self.history[config.HISTORY_SIZE:]
            self.on_history(text)

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

        icons = {"idle": "🎙", "recording": "🔴", "translating": "🌐",
                 "editing": "✏️", "noting": "📝", "processing": "⏳"}
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

        cleanup_item = rumps.MenuItem(
            f"AI Cleanup ({config.CLEANUP_MODEL})", callback=toggle_cleanup
        )
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

        # ── state → icon + overlay (dispatched to the main thread) ─────────
        def set_state(state):
            AppHelper.callAfter(setattr, app, "title", icons[state])
            if overlay is not None:
                if state == "recording":
                    overlay.recording()
                elif state == "translating":
                    overlay.recording(f"→ {config.TRANSLATE_TARGET}…")
                elif state == "editing":
                    overlay.recording("✎ instruction…")
                elif state == "noting":
                    overlay.recording("📝 note…")
                elif state == "processing":
                    overlay.processing()
                else:
                    overlay.hide()

        self.on_state = set_state

        def show_preview(text):
            if overlay is not None:
                overlay.recording(text)  # rolling live transcript in the pill

        self.on_preview = show_preview

        # ── menu: translate target picker ──────────────────────────────────
        target_menu = rumps.MenuItem("Translate to")
        target_items = {}

        def pick_target_cb(item):
            config.TRANSLATE_TARGET = item.title
            for title, entry in target_items.items():
                entry.state = title == item.title
            console.print(f"Translate target: {item.title}")

        for title in config.TRANSLATE_TARGETS:
            entry = rumps.MenuItem(title, callback=pick_target_cb)
            entry.state = title == config.TRANSLATE_TARGET
            target_menu.add(entry)
            target_items[title] = entry

        # ── menu: usage stats + AI habit report ────────────────────────────
        stats_menu = rumps.MenuItem("Stats")
        stats_today = rumps.MenuItem("…")
        stats_total = rumps.MenuItem("…")
        stats_mix = rumps.MenuItem("…")

        _report_title = "Generate AI usage report…"

        def gen_report(item):
            item.title = "Generating report… (~1 min)"
            item.set_callback(None)

            def work():
                try:
                    path = stats.generate_report(self.cleaner)
                    stats.open_report(path)
                    console.print(f"[green]Usage report → {path}[/]")
                finally:
                    def restore():
                        item.title = _report_title
                        item.set_callback(gen_report)
                    AppHelper.callAfter(restore)

            threading.Thread(target=work, daemon=True).start()

        _style_title = "Refresh style profile"

        def refresh_style(item):
            if self.cleaner is None:
                return
            item.title = "Learning your style…"
            item.set_callback(None)

            def work():
                try:
                    bullets = stats.build_style_profile(self.cleaner)
                    if bullets:
                        console.print(f"[green]Style profile updated:[/]\n{bullets}")
                    else:
                        console.print("[dim](not enough takes yet — need ≥30)[/]")
                finally:
                    def restore():
                        item.title = _style_title
                        item.set_callback(refresh_style)
                    AppHelper.callAfter(restore)

            threading.Thread(target=work, daemon=True).start()

        report_item = rumps.MenuItem(_report_title, callback=gen_report)
        style_item = rumps.MenuItem(_style_title, callback=refresh_style)
        for entry in (stats_today, stats_total, stats_mix, report_item, style_item):
            stats_menu.add(entry)

        def refresh_stats():
            s = stats.summary()
            stats_today.title = (
                f"Today: {s['today_takes']} takes · {s['today_chars']:,} chars"
            )
            stats_total.title = (
                f"All time: {s['takes']} takes · {s['chars']:,} chars"
                f" · ~{s['saved_min']:.0f} min saved"
            )
            stats_mix.title = (
                f"{s['cjk_pct']:.0f}% 中文"
                + (f" · top: {s['top_app']}" if s["top_app"] else "")
            )

        refresh_stats()

        prev_on_history = self.on_history

        def on_history_and_stats(text):
            prev_on_history(text)
            AppHelper.callAfter(refresh_stats)

        self.on_history = on_history_and_stats

        app.menu = [cleanup_item, target_menu, history_menu, stats_menu, None]  # None = separator

        threading.Thread(target=listener.run, daemon=True).start()
        app.run()


if __name__ == "__main__":
    try:
        DictationApp().run()
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/]")
