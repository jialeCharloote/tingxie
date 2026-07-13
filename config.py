"""Central configuration for the local Whisper Flow clone."""

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

# ── Personal dictionary ───────────────────────────────────────────────────────
# Post-STT find/replace for words the model keeps getting wrong (names, jargon).
# Rules file is created with examples on first run; edits apply live.
DICTIONARY_ENABLED = True
DICTIONARY_FILE = "~/.config/whisperflow/dictionary.json"

# ── Audio capture ─────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000  # Whisper expects 16kHz mono
CHANNELS = 1

# ── Recording modes (Phase 2) ─────────────────────────────────────────────────
# HOLD fn  (≥ TAP_THRESHOLD s)  -> push-to-talk: release to transcribe
# TAP fn   (< TAP_THRESHOLD s)  -> hands-free: keeps recording until you tap
#                                  again OR you stop talking (VAD auto-stop)
TAP_THRESHOLD = 0.35

VAD_ENABLED = True               # auto-stop hands-free mode on silence
VAD_MODEL = "models/silero_vad.onnx"
VAD_SILENCE = 1.8                # seconds of silence that ends the dictation
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

# ── Text injection ────────────────────────────────────────────────────────────
# "paste"  -> copy to clipboard and simulate Cmd+V (most reliable, default)
# "type"   -> synthesize keystrokes directly (works in Terminal/VS Code)
INJECT_METHOD = "paste"

# Restore the user's previous clipboard contents after pasting.
RESTORE_CLIPBOARD = True
