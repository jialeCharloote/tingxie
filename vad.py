"""Silero VAD monitor for hands-free mode.

Audio chunks are pushed onto a queue from the audio thread; a worker thread
feeds them to Silero VAD (via sherpa-onnx) and fires on_silence() once the
speaker has said something and then gone quiet for config.VAD_SILENCE seconds.
"""

import os
import queue
import threading

import sherpa_onnx

import config


def _make_detector():
    vad_config = sherpa_onnx.VadModelConfig()
    vad_config.silero_vad.model = os.path.join(
        os.path.dirname(__file__), config.VAD_MODEL
    )
    vad_config.silero_vad.threshold = config.VAD_THRESHOLD
    vad_config.silero_vad.min_silence_duration = config.VAD_SILENCE
    vad_config.silero_vad.min_speech_duration = 0.25
    vad_config.sample_rate = config.SAMPLE_RATE
    return sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=120)


class VadMonitor:
    """One monitor per hands-free session."""

    def __init__(self, on_silence):
        self.on_silence = on_silence
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def feed(self, chunk):
        """Called from the audio thread — just enqueue, no work here."""
        self._queue.put(chunk)

    def close(self):
        self._stop.set()

    def _worker(self):
        vad = _make_detector()
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            vad.accept_waveform(chunk)
            # A completed segment means: speech happened, then VAD_SILENCE of
            # quiet. That's our cue that the dictation is finished.
            if not vad.empty():
                self._stop.set()
                self.on_silence()
                return
