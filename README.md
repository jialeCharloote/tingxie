# Local Whisper Flow clone

**[中文文档 → README.zh.md](README.zh.md)**

A fully local, offline voice-to-text dictation tool for macOS (Apple Silicon).
Hold a hotkey, speak, release — your speech is transcribed on-device and pasted
into whatever app has focus. Nothing ever leaves your machine.

## Pipeline

```
fn → Mic (16kHz) → Silero VAD → SenseVoice STT → Ollama cleanup → paste into focused app
```

STT is **SenseVoice-Small** (Alibaba) via sherpa-onnx — built specifically for
Chinese/English code-switched speech (中英混杂), with punctuation and number
normalization built in. Measured: a 5.6s Chinese clip transcribes in **0.07s**
on this machine. Whisper (mlx / faster-whisper) remains available as alternate
backends in `config.py`.

### Model files

Models live in `models/` (not committed). To (re-)download SenseVoice and
Silero VAD in one go:

```bash
./download-models.sh
```

## Setup

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Then fetch the SenseVoice model (see "Model files" above) and, for the optional
LLM cleanup, install Ollama (see "LLM cleanup" below). After the one-time
downloads everything runs 100% offline.

## macOS permissions (required)

Grant these to your **terminal app** (Terminal / iTerm) in
**System Settings → Privacy & Security**:

| Permission        | Why                                    |
|-------------------|----------------------------------------|
| Microphone        | record your voice                      |
| Accessibility     | simulate Cmd+V to paste the text       |
| Input Monitoring  | capture the global hotkey              |

The first time you run it, macOS will prompt for Microphone and may prompt for
the others; if a keystroke silently does nothing, add the terminal under
Accessibility + Input Monitoring manually and restart it.

## Run

```bash
./.venv/bin/python main.py
```

Three ways to interact:

- **Hold fn** — push-to-talk: speak while holding, release to paste
- **Tap fn** — hands-free: speak freely, pause and think as long as you like;
  ends when you tap fn again (optional silence auto-stop via `VAD_ENABLED`)
- **Hold shift+fn** — translate mode, and it's bidirectional: speak 中文 → get
  English, speak English → get 中文. Pressing shift at any point *while*
  recording also toggles it — key order doesn't matter. Target language is
  switchable from the menu bar ("Translate to")
- **Hold option+fn** — voice-edit: select text anywhere first, then speak an
  instruction ("改得礼貌一点", "translate to English", "精简一半") — the
  selection is replaced with the edited version
- **Hold ctrl+fn** — voice note: the transcript is appended (timestamped) to
  `NOTES_FILE` instead of being pasted — capture a thought without switching
  windows
- **Double-tap fn** — toggle AI cleanup on/off (quick shortcut)
- **Esc** — cancel an in-progress recording; nothing gets pasted
- **Double-press Esc** (while idle) — retract the last dictation: deletes the
  just-pasted text (same app, within 2 minutes)

While you speak, the floating pill shows a **live rolling transcript** — the
take is re-transcribed every second (SenseVoice is fast enough that this is
free) so you see your words appear in real time.

While dictating, a floating pill at the bottom of the screen shows
**● Listening… / ⏳ Processing…** (above all windows, click-through, all Spaces).
The menu-bar icon mirrors state (🎙 / 🔴 / ⏳) and offers:

- **AI Cleanup (qwen2.5)** — toggle the LLM cleanup pass on/off live
- **Translate to** — pick the translate-mode target language
- **History** — the last 5 transcripts (persisted across sessions); click one to copy
- **Stats** — takes & characters today / all time, zh/en balance, top app, and
  **Generate AI usage report**: the local LLM analyzes your recent transcripts
  and reports your 口头禅, code-switching habits, common topics, and suggests
  personal-dictionary entries. Transcripts are logged to `TAKES_FILE` for this
  (100% local; `STATS_LOG_TEXT = False` disables it, deleting the file forgets
  everything)

Subtle start/stop sounds play on record start/end. Quit from the menu bar or
Ctrl+C in the terminal.

> **fn key setup:** set **System Settings → Keyboard → "Press 🌐 key to" =
> "Do Nothing"**, so holding fn doesn't also open the emoji picker or trigger
> macOS's built-in dictation.

To test just the hotkey without recording anything:

```bash
./.venv/bin/python hotkey.py   # prints DOWN/UP when you press fn
```

## Configuration

All knobs live in [`config.py`](config.py):

- `STT_BACKEND` — `sensevoice` (default, best for zh/en mixing) · `mlx`
  (Whisper on Apple GPU) · `faster-whisper` (Whisper on CPU)
- `HOTKEY` — `"fn"` (default, the 🌐 key) or any pynput chord like
  `"<ctrl>+<alt>+<space>"`
- `TAP_THRESHOLD` / `VAD_SILENCE` — tap-vs-hold split and the silence length
  that auto-ends a hands-free take
- `CLEANUP_ENABLED` / `CLEANUP_MODEL` — LLM polish toggle and Ollama model
- `CLEANUP_MIN_TOKENS` — skip the LLM pass for utterances shorter than this
  (CJK chars + English words; default 8, `0` = always clean)
- `DICTIONARY_ENABLED` / `DICTIONARY_FILE` — personal dictionary (see below)
- `TRANSLATE_ENABLED` / `TRANSLATE_TARGET` / `TRANSLATE_TARGET_ALT` — shift+fn
  translate mode; `_ALT` is the reverse direction when you speak English
- `EDIT_ENABLED` — option+fn voice-edit of selected text
- `NOTES_ENABLED` / `NOTES_FILE` — ctrl+fn voice notes
- `PREVIEW_ENABLED` / `PREVIEW_INTERVAL` / `OVERLAY_MAX_WIDTH` — live
  transcript in the pill and its width cap
- `RETRACT_WINDOW` — how long double-Esc can retract the last dictation
- `STATS_ENABLED` — usage stats in the menu (takes, chars, ~time saved)
- `INJECT_METHOD` — `paste` (default, most reliable) or `type` (direct keystrokes,
  good for Terminal/VS Code); `INJECT_OVERRIDES` switches method per app
  automatically (Terminal/iTerm/VS Code get `type` out of the box)
- `APP_TONES` — per-app tone for cleanup & translation: `casual` for chat apps
  (iMessage/WeChat/Slack/Discord preconfigured — 语气词 stay, no trailing
  period), `formal` for Mail/Outlook (full punctuation, fillers stripped hard)
- `TWO_STAGE_PASTE` — paste the raw transcript instantly, then swap in the
  LLM-cleaned version in place when it's ready (~1s). The swap self-cancels if
  you type, click, or switch apps in the meantime, so it never touches
  anything except the text it just pasted
- `SOUNDS_ENABLED` / `MENU_BAR` / `OVERLAY_ENABLED` — UX toggles

## Files

| File            | Role                                             |
|-----------------|--------------------------------------------------|
| `main.py`       | orchestration + menu bar                         |
| `hotkey.py`     | fn-key (Quartz event tap) / chord listeners      |
| `overlay.py`    | floating recording indicator (NSPanel)           |
| `vad.py`        | Silero VAD auto-stop for hands-free mode         |
| `cleanup.py`    | Ollama LLM transcript polish                     |
| `sounds.py`     | start/stop audio cues                            |
| `audio.py`      | microphone capture                               |
| `transcribe.py` | STT wrapper (SenseVoice / mlx / faster-whisper)  |
| `preview.py`    | live rolling transcript while recording          |
| `dictionary.py` | personal dictionary (post-STT find/replace)      |
| `stats.py`      | daily usage stats                                |
| `inject.py`     | clipboard-paste / keystroke injection, selection grab, retract |
| `config.py`     | all settings                                     |

## Translate mode

Hold **shift+fn** and speak — it's bidirectional: 中文 in, natural English
out; English in, 中文 out (`TRANSLATE_TARGET_ALT`). Great for writing English
email/Slack while thinking out loud in 中文. The overlay shows `● → English…`
and the menu-bar icon turns 🌐 so you always know which mode you're in; pick
a different target (e.g. 日本語) from the menu-bar **Translate to** submenu.
Uses the same local Ollama model as cleanup (filler words are dropped during
translation); on any failure it pastes the untranslated transcript instead of
losing your words.

## Adaptive style

With ≥30 takes in the corpus, the app distills a short **style profile** of
how you actually talk (which 语气词 you use, punctuation habits, which words
you keep in English) and injects it into every cleanup/translation — so the
polish stops flattening your voice: if you end messages with 哈/啦, they stay.
Refreshes automatically every `STYLE_REFRESH_EVERY` takes, or on demand via
**Stats → Refresh style profile**. Profile lives at `STYLE_FILE`; delete it to
reset, `STYLE_ADAPT = False` to disable.

## Personal dictionary

STT models fumble proper nouns (product names, coworkers, jargon). Fix them
once in `~/.config/whisperflow/dictionary.json` — created with examples on
first run — as `"wrong": "right"` pairs:

```json
{
  "cloud code": "Claude Code",
  "克劳德": "Claude"
}
```

Pure-ASCII keys match whole words case-insensitively (including at 中英 seams
like `用cloud code和`); keys containing CJK match exactly. Keys starting with
`_` are comments. Edits apply to the next dictation — no restart needed.

## LLM cleanup (Phase 3)

Transcripts are polished by a local LLM (`qwen2.5:7b` on Ollama): filler words
removed (嗯/呃/那个/um/uh), punctuation fixed, zh/en mixing preserved verbatim
(few-shot prompted — it will not translate). Adds ~1s per utterance, so short
utterances (under `CLEANUP_MIN_TOKENS`, default 8) skip it and paste instantly;
set `CLEANUP_ENABLED = False` to skip it entirely. `cleanup.py`
auto-starts `ollama serve` if it isn't running.

```bash
brew install ollama && ollama pull qwen2.5:7b   # one-time setup
```

## Start at login (optional)

A LaunchAgent plist is included but NOT installed. To enable:

```bash
cp com.whisperflow.dictation.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.whisperflow.dictation.plist
```

Note: running under launchd means macOS will re-prompt Microphone/Accessibility/
Input Monitoring permissions for the python binary itself. Logs go to
`/tmp/whisperflow.log`. To disable: `launchctl unload ~/Library/LaunchAgents/com.whisperflow.dictation.plist`.

## Tingxie.app — run as a real app bundle (recommended)

Running via the venv means the TCC permissions (Microphone / Accessibility /
Input Monitoring) are granted to the **Homebrew python binary** — a Homebrew
upgrade of python invalidates all three, and every other python script on the
machine inherits them. Packaging as a proper .app fixes that: `py2app`'s
launcher binary loads the embedded Python framework *in-process* (it doesn't
exec python), so the running process is `Tingxie.app/Contents/MacOS/Tingxie`
and macOS attaches the permissions to the bundle itself. (A shell-script
wrapper .app would **not** work — the process image would still be python.)

### Build

```bash
./make-app.sh          # → dist/Tingxie.app (~130MB), ad-hoc signed
```

The script uses `.venv` (installs the pure-python `py2app` into it on first
run), excludes the unused Whisper backends, and ad-hoc signs the bundle. The
230MB `models/` dir is **not** copied into the bundle — the app locates it via
(in order): `$TINGXIE_HOME`, `models/` next to the source when running from
the checkout, or `~/Library/Application Support/Tingxie/` (the build script
symlinks `models` there so double-clicking the app in Finder also works).

### Switch over from the venv LaunchAgent

```bash
ditto dist/Tingxie.app /Applications/Tingxie.app     # stable path for TCC

# stop + remove the old python-based agent
launchctl bootout gui/$UID/com.whisperflow.dictation
rm ~/Library/LaunchAgents/com.whisperflow.dictation.plist

# install + start the app-based agent
cp com.tingxie.dictation.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.tingxie.dictation.plist
```

Logs move to `/tmp/tingxie.log` / `/tmp/tingxie.err`. Restart later with
`launchctl kickstart -k gui/$UID/com.tingxie.dictation`.

**macOS will re-prompt all three permissions** — they now belong to
Tingxie.app, not python. On first launch: allow the **Accessibility** dialog,
then add **Tingxie** under **System Settings → Privacy & Security → Input
Monitoring** (the fn-key event tap needs it; if there's no prompt, add it
manually with the ＋ button by picking /Applications/Tingxie.app), and allow
**Microphone** on your first dictation. Restart the agent after granting:
permissions are only picked up at process start. The old grants for python
can be removed from those three panes afterwards.

Rebuilt the app? macOS keeps the grants as long as the bundle ID and path
stay the same (ad-hoc signatures change per build, so occasionally macOS asks
again — just re-allow).

### Validation checklist

- [ ] `tail -f /tmp/tingxie.log` shows `Ready.` and no traceback
- [ ] 🎙 icon appears in the menu bar
- [ ] hold fn → 🔴 + "Listening…" pill (Input Monitoring OK, Microphone prompt appears once)
- [ ] release → text pastes into the focused app (Accessibility OK)
- [ ] shift+fn → 中文 in, English out (Ollama reachable from launchd env)
- [ ] menu bar → History shows past transcripts (中文 reads back correctly)
- [ ] `launchctl kickstart -k gui/$UID/com.tingxie.dictation` → comes back to Ready

Rollback: `launchctl bootout gui/$UID/com.tingxie.dictation`, re-copy
`com.whisperflow.dictation.plist` into `~/Library/LaunchAgents/` and
`launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.whisperflow.dictation.plist`.
