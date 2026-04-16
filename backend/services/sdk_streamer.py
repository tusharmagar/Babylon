"""
Real-time laser streamer using BEYOND SDK.

Plays audio via sounddevice and streams laser frames to BEYOND
via the SDK DLL, perfectly synced to the audio clock.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from models.laser_types import LaserFrame
from services.beyond_sdk import BeyondSDK


class SdkStreamer:
    """Streams pre-generated LaserFrames to BEYOND SDK in sync with audio."""

    def __init__(self):
        self.sdk = BeyondSDK()
        self.frames: list[LaserFrame] = []
        self.audio_data: np.ndarray | None = None
        self.audio_sr: int = 44100
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._audio_stream = None
        self._audio_position: int = 0
        self.playing = False
        self.current_time_ms: float = 0.0
        self.total_duration_ms: float = 0.0
        self.frames_sent: int = 0
        self.error: str | None = None

    def load(self, frames: list[LaserFrame], audio_path: Path) -> bool:
        """Load frames and audio for playback."""
        try:
            self.frames = frames
            self.audio_data, self.audio_sr = sf.read(str(audio_path), dtype="float32")
            if self.frames:
                self.total_duration_ms = self.frames[-1].timestamp_ms + 33.33
            return True
        except Exception as e:
            self.error = f"Load failed: {e}"
            return False

    def start(self) -> bool:
        """Start synced audio + SDK frame streaming."""
        if not self.frames or self.audio_data is None:
            self.error = "No data loaded"
            return False

        # Connect SDK
        if not self.sdk.ready:
            if not self.sdk.connect():
                self.error = "Could not connect to BEYOND SDK"
                return False

        self.sdk.create_image("BabylonSync")

        self._stop_event.clear()
        self._audio_position = 0
        self.playing = True
        self.frames_sent = 0
        self.error = None

        # Start audio
        channels = 1 if self.audio_data.ndim == 1 else self.audio_data.shape[1]
        self._audio_stream = sd.OutputStream(
            samplerate=self.audio_sr,
            channels=channels,
            callback=self._audio_callback,
            blocksize=1024,
        )
        self._audio_stream.start()

        # Start frame streaming thread
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

        return True

    def _audio_callback(self, outdata, frames, time_info, status):
        """sounddevice callback — fills audio buffer and tracks position."""
        if self.audio_data is None:
            outdata.fill(0)
            return

        start = self._audio_position
        end = start + frames

        if end > len(self.audio_data):
            remaining = len(self.audio_data) - start
            if remaining > 0:
                outdata[:remaining] = self.audio_data[start:start + remaining]
            outdata[remaining:] = 0
            self._stop_event.set()
        else:
            outdata[:] = self.audio_data[start:end]

        self._audio_position = end

    def _get_audio_time_ms(self) -> float:
        return (self._audio_position / self.audio_sr) * 1000.0

    def _find_frame(self, time_ms: float) -> LaserFrame | None:
        """Binary search for the frame at the given timestamp."""
        if not self.frames:
            return None
        lo, hi = 0, len(self.frames) - 1
        while lo < hi:
            mid = (lo + hi + 1) >> 1
            if self.frames[mid].timestamp_ms <= time_ms:
                lo = mid
            else:
                hi = mid - 1
        return self.frames[lo]

    def _stream_loop(self):
        """Main loop: sync frames to audio clock, push to SDK."""
        fps = 30
        frame_interval = 1.0 / fps

        while not self._stop_event.is_set():
            loop_start = time.perf_counter()

            time_ms = self._get_audio_time_ms()
            self.current_time_ms = time_ms

            frame = self._find_frame(time_ms)
            if frame and frame.points:
                self.sdk.send_frame(frame.points)
                self.frames_sent += 1

            elapsed = time.perf_counter() - loop_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.playing = False

    def stop(self):
        """Stop playback and clean up."""
        self._stop_event.set()

        if self._audio_stream:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        self.sdk.blackout()
        self.playing = False
        self.current_time_ms = 0

    def get_status(self) -> dict:
        return {
            "playing": self.playing,
            "current_time_ms": self.current_time_ms,
            "total_duration_ms": self.total_duration_ms,
            "frames_sent": self.frames_sent,
            "sdk": self.sdk.get_status(),
            "error": self.error,
        }

    def shutdown(self):
        """Full shutdown including SDK disconnect."""
        self.stop()
        self.sdk.disconnect()
