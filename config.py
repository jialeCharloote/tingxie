"""Central configuration for the local Whisper Flow clone."""

import os

# ── Paths ─────────────────────────────────────────────────────────────────────
# Where models/ lives. Running from a source checkout that's the repo itself,
# but inside Tingxie.app the code sits in the bundle with no models/ next to
# it — there we use $TINGXIE_HOME (set in the LaunchAgent plist) or, failing
# that, ~/Library/Application Support/Tingxie (make-app.sh symlinks models/
# there so Finder launches work too).


def _base_dir():
    env = os.environ.get("TINGXIE_HOME")
    if env:
        return os.path.expanduser(env)
    src = os.path.dirname(os.path.abspath(__file__))
    if os.path.isdir(os.path.join(src, "models")):
        return src
    return os.path.expanduser("~/Library/Application Support/Tingxie")


BASE_DIR = _base_dir()

# ── Speech-to-text ────────────────────────────────────────────────────────────
# Backend:
#   "sensevoice"     — Alibaba SenseVoice-Small via sherpa-onnx. Built for
#                      Chinese/English code-switching (中英混杂), ~30x faster
#                      than Whisper here (0.07s for a 5.6s clip). DEFAULT.
#   "mlx"            — Whisper on the Apple GPU (Metal)
#   "faster-whisper" — Whisper on CPU
STT_BACKEND = "sensevoice"

# SenseVoice model files (downloaded from k2-fsa/sherpa-onnx releases).
SENSEVOICE_DIR = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SENSEVOICE_LANGUAGE = "auto"   # auto-detects zh/en per utterance, handles mixing
SENSEVOICE_THREADS = 4

# IMPORTANT: use a MULTILINGUAL model (no ".en" suffix) — we dictate in mixed
# Chinese + English (中英混杂). large-v3-turbo is the sweet spot for zh/en:
# near large-v3 accuracy at a fraction of its cost. For lower latency at the
# price of zh accuracy, try "mlx-community/whisper-small" / "whisper-medium".
STT_MODEL_MLX = "mlx-community/whisper-large-v3-turbo"

# faster-whisper (CPU) fallback settings.
STT_MODEL = "large-v3-turbo"
STT_COMPUTE_TYPE = "int8"
STT_DEVICE = "cpu"

# Language hint. "zh" works best for mixed Chinese/English speech: Whisper's
# Chinese mode transcribes embedded English words/terms in Latin script as-is.
# Set to None for per-utterance autodetect (can misfire on short clips).
STT_LANGUAGE = "zh"

# Bias the decoder toward Simplified Chinese with natural mixed-in English.
# Without this, Whisper sometimes outputs Traditional characters.
STT_INITIAL_PROMPT = "以下是普通话的句子，中英文混合，使用简体中文。"

# ── LLM cleanup (Phase 3) ─────────────────────────────────────────────────────
# Post-process the transcript with a local LLM: remove filler words (嗯/呃/um),
# fix punctuation, keep zh/en mixing intact. Adds some latency per utterance.
CLEANUP_ENABLED = True
OLLAMA_HOST = "localhost:11434"
CLEANUP_MODEL = "qwen2.5:7b"     # best local model for mixed zh/en text
CLEANUP_KEEP_ALIVE = "30m"       # keep model warm in RAM between dictations
CLEANUP_TIMEOUT = 20             # seconds; on timeout we paste the raw text

# Skip the LLM pass for short utterances — quick replies ("好的 sounds good")
# paste instantly, only longer dictations pay the ~1s polish. Length is counted
# as CJK characters + English words; 0 = always clean.
CLEANUP_MIN_TOKENS = 8

# ── Translation mode ──────────────────────────────────────────────────────────
# Hold SHIFT+fn to dictate in one language and paste the translation: speak
# 中文 (or mixed zh/en), get natural English. Uses the same Ollama model as
# cleanup; needs Ollama available even if CLEANUP_ENABLED is False.
TRANSLATE_ENABLED = True
TRANSLATE_TARGET = "English"     # any language the model knows ("日本語", …)
TRANSLATE_TIMEOUT = 30           # seconds; on timeout we paste the untranslated text

# Bidirectional: when the transcript is already mostly in Latin script (i.e.
# you spoke English), translate to this instead of TRANSLATE_TARGET.
TRANSLATE_TARGET_ALT = "中文(简体)"
# Choices offered in the menu-bar "Translate to" picker.
TRANSLATE_TARGETS = ["English", "中文(简体)", "日本語"]

# ── Voice-edit mode (fn+option) ───────────────────────────────────────────────
# Select text anywhere, hold OPTION+fn, and speak an instruction ("改得礼貌
# 一点", "translate to English", "精简一半") — the selection is replaced by
# the edited version. Needs Ollama.
EDIT_ENABLED = True
EDIT_TIMEOUT = 45                # editing long selections takes the LLM longer

# ── Voice notes (fn+ctrl) ─────────────────────────────────────────────────────
# Hold CTRL+fn: the transcript is appended (timestamped) to NOTES_FILE instead
# of being pasted — quick capture without switching windows.
NOTES_ENABLED = True
NOTES_FILE = "~/Documents/voice-notes.md"

# ── Personal dictionary ───────────────────────────────────────────────────────
# Post-STT find/replace for words the model keeps getting wrong (names, jargon).
# Rules file is created with examples on first run; edits apply live.
DICTIONARY_ENABLED = True
DICTIONARY_FILE = "~/.config/whisperflow/dictionary.json"

# Fuzzy matching: after the exact pass, also fix near-misses the model produced
# that you never enumerated (e.g. dict has "cloud code", STT emits "cloude code").
# Only kicks in for keys ≥ DICTIONARY_FUZZY_MIN_LEN chars, and only replaces spans
# whose similarity to a key is ≥ DICTIONARY_FUZZY_THRESHOLD (0-1). Short keys are
# skipped because a low bar over 2-3 chars mangles legitimate words.
DICTIONARY_FUZZY = True
DICTIONARY_FUZZY_THRESHOLD = 0.75
DICTIONARY_FUZZY_MIN_LEN = 4

# ── Audio capture ─────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000  # Whisper expects 16kHz mono
CHANNELS = 1

# ── Recording modes (Phase 2) ─────────────────────────────────────────────────
# HOLD fn  (≥ TAP_THRESHOLD s)  -> push-to-talk: release to transcribe
# TAP fn   (< TAP_THRESHOLD s)  -> hands-free: keeps recording until you tap
#                                  again OR you stop talking (VAD auto-stop)
TAP_THRESHOLD = 0.35

# Auto-stop hands-free mode on silence. OFF by default: getting cut off while
# you pause to think is worse than tapping fn to finish — a hands-free take
# now ends ONLY when you tap fn again (or Esc to cancel). Set True to get
# silence auto-stop back.
VAD_ENABLED = False
VAD_MODEL = "models/silero_vad.onnx"
# Seconds of silence that ends a hands-free take (only when VAD_ENABLED).
VAD_SILENCE = 3.0
VAD_THRESHOLD = 0.5              # speech probability threshold

# ── Hotkey ────────────────────────────────────────────────────────────────────
# Push-to-talk: hold this key to record, release to transcribe + paste.
#   "fn"                      -> the fn/🌐 key (like Wispr Flow; macOS only)
#   "<ctrl>+<alt>+<space>"    -> any pynput chord also works
# For "fn": set System Settings > Keyboard > "Press 🌐 key to" = "Do Nothing"
# so holding it doesn't also pop the emoji picker or macOS dictation.
HOTKEY = "fn"

# ── UX (Phase 4) ──────────────────────────────────────────────────────────────
SOUNDS_ENABLED = True    # subtle pop/tink cues on record start/stop
MENU_BAR = True          # show a menu-bar icon (🎙 idle / 🔴 recording)
OVERLAY_ENABLED = True   # floating "正在听…" pill at the bottom of the screen
HISTORY_SIZE = 5         # recent transcripts kept in the menu (click to copy)

# Live transcript preview: while you speak, the pill shows the rolling text
# (the whole take is re-transcribed every PREVIEW_INTERVAL seconds — SenseVoice
# is fast enough that this costs almost nothing).
PREVIEW_ENABLED = True
PREVIEW_INTERVAL = 1.0
OVERLAY_MAX_WIDTH = 300  # px cap for the pill; long previews show the tail

# Double-press Esc (while idle) to retract the last dictation: selects back
# over the just-pasted text and deletes it. Only within RETRACT_WINDOW seconds
# and only if you're still in the same app.
RETRACT_WINDOW = 120

# Usage stats (menu bar): takes + characters per day, estimated typing time
# saved (vs ~80 chars/min hand-typing).
STATS_ENABLED = True
STATS_FILE = "~/.config/whisperflow/stats.json"

# Habit analytics: every take (text included) is appended to TAKES_FILE so
# "Generate AI usage report" can learn your口头禅, zh/en mixing habits, and
# suggest personal-dictionary entries. 100% local — nothing ever leaves this
# machine. Set STATS_LOG_TEXT = False to stop collecting transcripts; delete
# TAKES_FILE to forget history.
STATS_LOG_TEXT = True
TAKES_FILE = "~/.config/whisperflow/takes.jsonl"
REPORT_FILE = "~/.config/whisperflow/usage-report.md"
ANALYZE_TIMEOUT = 180            # the report LLM call chews a lot of text

# ── Adaptive style ────────────────────────────────────────────────────────────
# Distill YOUR speaking style from the transcript corpus into a short profile
# (needs ≥30 takes) and let cleanup/translation respect it — 语气词 you like,
# punctuation habits, words you keep in English. Auto-refreshes every
# STYLE_REFRESH_EVERY takes; "Refresh style profile" in the menu forces it;
# delete STYLE_FILE to reset.
STYLE_ADAPT = True
STYLE_FILE = "~/.config/whisperflow/style-profile.md"
STYLE_REFRESH_EVERY = 100

# ── Text injection ────────────────────────────────────────────────────────────
# "paste"  -> copy to clipboard and simulate Cmd+V (most reliable, default)
# "type"   -> synthesize keystrokes directly (works in Terminal/VS Code)
INJECT_METHOD = "paste"

# Per-app overrides: frontmost app's bundle id (substring match) -> method.
# Terminals swallow Cmd+V oddly under some setups; direct keystrokes are safer.
INJECT_OVERRIDES = {
    "com.apple.Terminal": "type",
    "com.googlecode.iterm2": "type",
    "com.microsoft.VSCode": "type",
}

# ── Per-app tone ──────────────────────────────────────────────────────────────
# Adapt the LLM pass (cleanup AND translation) to where you're dictating:
# bundle-id substring -> tone. "casual" keeps the chatty vibe (语气词 stay, no
# trailing period — texting style); "formal" produces polished full sentences.
# Apps not listed get the neutral default behavior.
APP_TONES = {
    "com.apple.MobileSMS": "casual",        # iMessage
    "com.tencent.xinWeChat": "casual",      # WeChat 微信
    "com.tinyspeck.slackmacgap": "casual",  # Slack
    "com.hnc.Discord": "casual",
    "com.apple.mail": "formal",
    "com.microsoft.Outlook": "formal",
}

# ── Two-stage paste ───────────────────────────────────────────────────────────
# Paste the raw transcript INSTANTLY, then swap in the LLM-cleaned version in
# place once it's ready (~1s later) — zero perceived latency, full polish.
# The swap self-cancels if you type, click, or switch apps in between, so it
# only ever touches the text it just pasted. Not used for translate mode,
# "type" injection, multi-line takes, or takes over TWO_STAGE_MAX_CHARS.
TWO_STAGE_PASTE = True
TWO_STAGE_MAX_CHARS = 150

# Restore the user's previous clipboard contents after pasting.
RESTORE_CLIPBOARD = True
