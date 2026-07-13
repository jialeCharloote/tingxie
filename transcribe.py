"""Local speech-to-text. Runs fully offline once models are cached.

Backends:
  - "sensevoice":     Alibaba SenseVoice-Small via sherpa-onnx — built for
                      zh/en code-switching, by far the fastest (default)
  - "mlx":            mlx-whisper on the Apple GPU (Metal)
  - "faster-whisper": CTranslate2 on CPU — portable fallback
"""

import os
import threading

import config


class Transcriber:
    def __init__(self):
        # Preview (of a new take) and final decode (of the previous take) can
        # overlap now that processing is async — never decode concurrently.
        self._decode_lock = threading.Lock()
        self.backend = config.STT_BACKEND
        if self.backend == "sensevoice":
            import sherpa_onnx

            d = os.path.join(config.BASE_DIR, config.SENSEVOICE_DIR)
            self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=os.path.join(d, "model.int8.onnx"),
                tokens=os.path.join(d, "tokens.txt"),
                language=config.SENSEVOICE_LANGUAGE,
                use_itn=True,  # inverse text normalization: numbers, punctuation
                num_threads=config.SENSEVOICE_THREADS,
            )
        elif self.backend == "mlx":
            import mlx_whisper  # noqa: F401 — imported here to fail fast

            self._mlx = mlx_whisper
            # Warm up: first call compiles kernels and loads weights.
            import numpy as np

            self._mlx.transcribe(
                np.zeros(8000, dtype=np.float32),
                path_or_hf_repo=config.STT_MODEL_MLX,
            )
        else:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                config.STT_MODEL,
                device=config.STT_DEVICE,
                compute_type=config.STT_COMPUTE_TYPE,
            )

    def transcribe(self, audio):
        """Take a float32 mono 16kHz numpy array, return the transcript string."""
        if audio is None or len(audio) == 0:
            return ""
        if self.backend == "sensevoice":
            with self._decode_lock:
                stream = self._rec.create_stream()
                stream.accept_waveform(config.SAMPLE_RATE, audio)
                self._rec.decode_stream(stream)
                return stream.result.text.strip()
        if self.backend == "mlx":
            result = self._mlx.transcribe(
                audio,
                path_or_hf_repo=config.STT_MODEL_MLX,
                language=config.STT_LANGUAGE,
                initial_prompt=config.STT_INITIAL_PROMPT,
            )
            return result["text"].strip()
        segments, _info = self.model.transcribe(
            audio,
            language=config.STT_LANGUAGE,
            initial_prompt=config.STT_INITIAL_PROMPT,
            vad_filter=True,  # built-in Silero VAD: trims silence
            beam_size=5,
        )
        return "".join(seg.text for seg in segments).strip()
