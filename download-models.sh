#!/usr/bin/env bash
# One-shot download of the model files (not committed to the repo):
#   - SenseVoice-Small (zh/en/ja/ko/yue STT) for sherpa-onnx
#   - Silero VAD (hands-free auto-stop)
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p models
cd models

SENSEVOICE=sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
if [ ! -d "$SENSEVOICE" ]; then
  echo "Downloading SenseVoice-Small (~230MB)…"
  curl -sLO "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$SENSEVOICE.tar.bz2"
  tar xjf "$SENSEVOICE.tar.bz2" && rm "$SENSEVOICE.tar.bz2"
else
  echo "SenseVoice already present — skipping."
fi

if [ ! -f silero_vad.onnx ]; then
  echo "Downloading Silero VAD…"
  curl -sLO "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx"
else
  echo "Silero VAD already present — skipping."
fi

echo "Done. Models are in $(pwd)"
