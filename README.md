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

SenseVoice lives in `models/` (not committed). To re-download:

```bash
mkdir -p models && cd models
curl -sLO https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xjf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2 && rm *.tar.bz2
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
- **Tap fn** — hands-free: speak freely; ends when you tap fn again or go
  quiet for ~2s (Silero VAD auto-stop)
- **Double-tap fn** — toggle AI cleanup on/off (quick shortcut)

While dictating, a floating pill at the bottom of the screen shows
**● Listening… / ⏳ Processing…** (above all windows, click-through, all Spaces).
The menu-bar icon mirrors state (🎙 / 🔴 / ⏳) and offers:

- **AI Cleanup (qwen2.5)** — toggle the LLM cleanup pass on/off live
- **History** — the last 5 transcripts (persisted across sessions); click one to copy

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
- `INJECT_METHOD` — `paste` (default, most reliable) or `type` (direct keystrokes,
  good for Terminal/VS Code)
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
| `inject.py`     | clipboard-paste / keystroke text injection       |
| `config.py`     | all settings                                     |

## LLM cleanup (Phase 3)

Transcripts are polished by a local LLM (`qwen2.5:7b` on Ollama): filler words
removed (嗯/呃/那个/um/uh), punctuation fixed, zh/en mixing preserved verbatim
(few-shot prompted — it will not translate). Adds ~1s per utterance; set
`CLEANUP_ENABLED = False` to paste raw transcripts instantly. `cleanup.py`
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
