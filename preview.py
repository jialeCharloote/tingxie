"""Live transcript preview — re-transcribe the growing buffer while recording.

SenseVoice is fast enough (~0.01x realtime) to redo the whole take every
second; the rolling text streams into the overlay pill so you see your words
appear as you speak. Nothing here touches what finally gets pasted.
"""

import threading

import config


class Preview:
    def __init__(self, recorder, transcriber, on_text):
        self._recorder = recorder
        self._transcriber = transcriber
        self._on_text = on_text
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        last = ""
        while not self._stop.wait(config.PREVIEW_INTERVAL):
            audio = self._recorder.snapshot()
            if len(audio) < config.SAMPLE_RATE // 2:
                continue  # <0.5s of audio decodes to junk
            text = self._transcriber.transcribe(audio)
            if self._stop.is_set():
                break  # take already ended — don't flash stale text
            if text and text != last:
                last = text
                self._on_text(text)
            # Long takes re-decode more audio each pass; stretch the interval
            # so preview CPU stays bounded (~5% of the take length per pass).
            extra = len(audio) / config.SAMPLE_RATE * 0.05 - config.PREVIEW_INTERVAL
            if extra > 0 and self._stop.wait(extra):
                break

    def stop(self):
        """Signal the loop to exit and wait for any in-flight decode to finish,
        so the final transcription never runs concurrently with a preview."""
        self._stop.set()
        self._thread.join(timeout=3)
