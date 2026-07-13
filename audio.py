"""Microphone capture. Records into a buffer while the hotkey is held."""

import numpy as np
import sounddevice as sd

import config


class Recorder:
    """Streams mic audio into an in-memory buffer between start() and stop()."""

    def __init__(self, sample_rate=config.SAMPLE_RATE, channels=config.CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self._frames = []
        self._stream = None
        self._on_chunk = None

    def _callback(self, indata, frames, time_info, status):
        # Called by sounddevice on its own thread for each audio block.
        chunk = indata.copy()
        self._frames.append(chunk)
        if self._on_chunk is not None:
            self._on_chunk(chunk.flatten())

    def start(self, on_chunk=None):
        """Begin capture. on_chunk (optional) receives each block as float32
        mono — used by the VAD monitor. Runs on the audio thread: keep it cheap."""
        self._frames = []
        self._on_chunk = on_chunk
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=512,  # Silero VAD window size at 16kHz
            callback=self._callback,
        )
        self._stream.start()

    def snapshot(self):
        """Copy of everything recorded so far, without stopping the stream.
        Safe to call from another thread (list append is atomic)."""
        frames = self._frames[:]
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames, axis=0).flatten().astype(np.float32)

    def stop(self):
        """Stop recording and return the audio as a float32 mono numpy array."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._frames, axis=0).flatten()
        return audio.astype(np.float32)
