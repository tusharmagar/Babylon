"""
BEYOND SDK Manager — uses asyncio event loop for frame sending (not threads).

The DLL returns result=2 from daemon threads but result=1 from the main thread.
So we send frames via an asyncio task on the main event loop, matching the
approach that works in babylon-laser and our test-circle endpoint.
"""

import asyncio
import ctypes
import time
import socket
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class SdkPoint(ctypes.Structure):
    """16-byte point struct matching the SDK exactly."""
    _fields_ = [
        ('x', ctypes.c_float),
        ('y', ctypes.c_float),
        ('z', ctypes.c_float),
        ('color', ctypes.c_uint32),
        ('rep_count', ctypes.c_uint8),
        ('focus', ctypes.c_uint8),
        ('status', ctypes.c_uint8),
        ('zero', ctypes.c_uint8),
    ]


DLL_PATH = r"C:\Program Files\MadMapper 5.7.1\BEYONDIOx64.dll"
# Use a unique image name per server run — BEYOND caches stale handles otherwise
import uuid as _uuid
IMAGE_NAME = f"Babylon_{_uuid.uuid4().hex[:8]}".encode("ascii")
SCAN_RATE = -30000
TARGET_FPS = 30


def _clear_cues_sync_localhost():
    """Fallback: try localhost PangoScript directly."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(("localhost", 16063))
        sock.sendall(b"StopAllNow\r\n")
        try:
            resp = sock.recv(1024).decode("ascii", errors="replace").strip()
            logger.info(f"SDK: PangoScript (localhost) StopAllNow -> {resp}")
        except socket.timeout:
            pass
        sock.close()
    except Exception as e:
        logger.warning(f"SDK: Localhost PangoScript skipped: {e}")


# Set by server.py after both managers are created — used to send StopAllNow
# through the already-connected TCP socket (works with ngrok/remote BEYOND)
_connected_beyond_manager = None


def set_beyond_manager(mgr):
    """Inject the BeyondConnectionManager so SDK can use its live socket for StopAllNow."""
    global _connected_beyond_manager
    _connected_beyond_manager = mgr


async def clear_cues_via_pangoscript():
    """Clear cues — prefer the live connection, fallback to localhost. Always time-bounded."""
    try:
        await asyncio.wait_for(_clear_cues_inner(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning("SDK: clear_cues timed out — proceeding anyway")
    except Exception as e:
        logger.warning(f"SDK: clear_cues failed ({e}) — proceeding anyway")


async def _clear_cues_inner():
    mgr = _connected_beyond_manager
    if mgr is not None and getattr(mgr, "connected", False):
        try:
            result = await mgr.send_command("StopAllNow")
            if result.get("success"):
                logger.info(f"SDK: StopAllNow via live connection -> {result.get('response')}")
                return
        except Exception as e:
            logger.warning(f"SDK: Live StopAllNow failed ({e}), falling back to localhost")

    # Fallback: try localhost
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _clear_cues_sync_localhost)


class BeyondSDKManager:
    """
    Manages BEYOND SDK with asyncio-based frame sending.
    All DLL calls happen on the main event loop thread.
    """

    def __init__(self):
        self._dll = None
        self._image_name = None
        self._ready = False
        self._zone_arr = (ctypes.c_ubyte * 256)()
        self._zone_arr[0] = 1

        self.initialized = False
        self.simulation_mode = False
        self.current_points = []
        self.current_pattern_name = ""
        self.running = False
        self._task = None
        self.frames_sent = 0
        self.last_error = None
        # GIF playback state
        self.gif_active = False
        self._gif_frames = []  # list of (ctypes array, length)
        self._gif_durations_ms = []
        self._gif_task = None
        self.current_gif_name = ""
        # Song playback state (SDK-streamed laser frames synced to audio)
        self.song_active = False
        self._song_frames_packed = []  # list of (ctypes array, length)
        self._song_timestamps_ms = []  # parallel list of frame.timestamp_ms
        self._song_task = None
        self._song_audio_stream = None
        self._song_audio_data = None
        self._song_audio_sr = 44100
        self._song_audio_position = 0
        self._song_stop_event = None
        self.current_song_name = ""
        self.song_total_ms = 0.0
        self.song_frames_sent = 0

    def initialize(self):
        """Connect to SDK and create image. Call start_send_loop() after event loop is running."""
        try:
            if not os.path.exists(DLL_PATH):
                logger.warning(f"SDK: DLL not found at {DLL_PATH} — simulation mode")
                self.simulation_mode = True
                self.initialized = True
                return True

            self._dll = ctypes.CDLL(DLL_PATH)

            # Function signatures (matches babylon-laser)
            self._dll.ldbCreateZoneImage.argtypes = [ctypes.c_int, ctypes.c_char_p]
            self._dll.ldbCreateZoneImage.restype = ctypes.c_int
            self._dll.ldbDeleteZoneImage.argtypes = [ctypes.c_char_p]
            self._dll.ldbSendFrameToImage.argtypes = [
                ctypes.c_char_p, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ]
            self._dll.ldbSendFrameToImage.restype = ctypes.c_int
            self._dll.ldbEnableLaserOutput.restype = ctypes.c_int
            self._dll.ldbBlackout.restype = ctypes.c_int
            self._dll.ldbDestroy.restype = ctypes.c_int
            self._dll.ldbGetProjectorCount.restype = ctypes.c_int
            self._dll.ldbGetZoneCount.restype = ctypes.c_int

            self._dll.ldbCreate()

            for _ in range(50):
                if self._dll.ldbBeyondExeReady():
                    break
                time.sleep(0.1)

            if not self._dll.ldbBeyondExeReady():
                logger.error("SDK: BEYOND not ready — simulation mode")
                self.last_error = "BEYOND not ready — is it running?"
                self.simulation_mode = True
                self.initialized = True
                return True

            self._ready = True
            projectors = self._dll.ldbGetProjectorCount()
            zones = self._dll.ldbGetZoneCount()
            logger.info(f"SDK: Connected! projectors={projectors} zones={zones}")

            self._image_name = IMAGE_NAME
            result = self._dll.ldbCreateZoneImage(0, self._image_name)
            self._dll.ldbEnableLaserOutput()
            logger.info(f"SDK: CreateZoneImage={result}, laser output enabled")

            self.initialized = True
            self.simulation_mode = False
            return True

        except OSError as e:
            logger.warning(f"SDK: Could not load DLL ({e}) — simulation mode")
            self.simulation_mode = True
            self.initialized = True
            return True
        except Exception as e:
            logger.error(f"SDK: Init failed: {e}")
            self.last_error = str(e)
            self.simulation_mode = True
            self.initialized = True
            return True

    def start_send_loop(self):
        """Start the asyncio send loop. Must be called after the event loop is running."""
        self.running = True
        self._task = asyncio.create_task(self._send_loop())
        logger.info(f"SDK: Asyncio send loop started (simulation={self.simulation_mode})")

    def _build_and_send_frame(self, points):
        """Build SdkPoint array and send to DLL. Runs in executor thread."""
        n = min(len(points), 8192)
        arr = (SdkPoint * n)()

        for i in range(n):
            p = points[i]
            arr[i].x = float(p.get('x', 0))
            arr[i].y = float(p.get('y', 0))
            arr[i].z = 0.0

            color = p.get('color', 0)
            if isinstance(color, str):
                try:
                    color = int(color, 16) if color.startswith('0x') else int(color)
                except (ValueError, TypeError):
                    color = 0
            arr[i].color = int(color) & 0xFFFFFFFF
            arr[i].rep_count = int(p.get('rep_count', 0))
            arr[i].focus = 0
            arr[i].status = 0
            arr[i].zero = 0

        result = self._dll.ldbSendFrameToImage(
            self._image_name, n,
            ctypes.byref(arr), ctypes.byref(self._zone_arr),
            SCAN_RATE,
        )
        return n, result

    async def _send_loop(self):
        """Async 30fps loop — DLL calls run via the event loop, yielding between frames."""
        frame_time = 1.0 / TARGET_FPS
        loop = asyncio.get_event_loop()
        consecutive_errors = 0

        while self.running:
          try:
            # Skip this loop when GIF or song playback is active — their task owns the DLL
            if self.gif_active or self.song_active:
                await asyncio.sleep(0.05)
                continue

            loop_start = time.time()

            points = self.current_points

            if points and self._ready and self._dll and self._image_name:
                try:
                    n, result = self._build_and_send_frame(points)
                    self.frames_sent += 1

                    if self.frames_sent == 1 or self.frames_sent % 300 == 0:
                        logger.info(
                            f"SDK SEND: frame #{self.frames_sent}, {n} pts, result={result}"
                        )

                except Exception as e:
                    if self.frames_sent % 300 == 0:
                        logger.error(f"SDK: Frame error: {e}")

            elif points and self.simulation_mode:
                self.frames_sent += 1

            elapsed = time.time() - loop_start
            sleep_time = frame_time - elapsed
            await asyncio.sleep(max(sleep_time, 0.001))  # Always yield
            consecutive_errors = 0
          except asyncio.CancelledError:
            raise
          except Exception as e:
            consecutive_errors += 1
            logger.error(f"SDK send loop error (#{consecutive_errors}): {e}", exc_info=True)
            await asyncio.sleep(0.1)
            # If something is very wrong, sleep longer but don't die
            if consecutive_errors > 10:
                await asyncio.sleep(1.0)

    def _refresh_zone_image(self):
        """Delete + recreate the zone image to force a clean DLL state.

        After stopping content, BEYOND's zone image handle can go stale and
        subsequent ldbSendFrameToImage calls return result=2. Recreating the
        image every time we start new content avoids that.
        """
        if not self._dll or not self._ready:
            return
        try:
            self._dll.ldbDeleteZoneImage(self._image_name)
        except Exception as e:
            logger.debug(f"SDK: delete zone image skipped ({e})")
        try:
            r = self._dll.ldbCreateZoneImage(0, self._image_name)
            self._dll.ldbEnableLaserOutput()
            logger.info(f"SDK: zone image refreshed (CreateZoneImage={r})")
        except Exception as e:
            logger.warning(f"SDK: refresh zone image failed: {e}")

    async def set_points(self, points, pattern_name=""):
        """Swap the point list. Clear cues first so SDK output is visible."""
        if points and self._ready:
            await clear_cues_via_pangoscript()
            self._refresh_zone_image()
        self.current_points = points
        self.current_pattern_name = pattern_name
        logger.info(f"SDK: Points updated — {len(points)} pts, pattern={pattern_name!r}")

    async def play_gif(self, frames_points, durations_ms, gif_name=""):
        """Play a GIF — cycle through pre-vectorized frames at their native durations.

        frames_points: list of lists of (x, y, color) tuples
        durations_ms: parallel list of per-frame durations
        """
        # Stop any currently playing GIF
        await self.stop_gif()

        if self._ready:
            await clear_cues_via_pangoscript()
            try:
                self._dll.ldbEnableLaserOutput()
            except Exception:
                pass

        # Pre-pack each frame into ctypes arrays (done once, reused in loop)
        packed = []
        for pts in frames_points:
            n = min(len(pts), 8192)
            arr = (SdkPoint * n)()
            for i in range(n):
                x, y, color = pts[i]
                arr[i].x = float(x)
                arr[i].y = float(y)
                arr[i].z = 0.0
                arr[i].color = int(color) & 0xFFFFFFFF
                arr[i].rep_count = 0
                arr[i].focus = 0
                arr[i].status = 0
                arr[i].zero = 0
            packed.append((arr, n))

        self._gif_frames = packed
        self._gif_durations_ms = durations_ms
        self.current_gif_name = gif_name
        self.gif_active = True
        self._gif_task = asyncio.create_task(self._gif_loop())
        logger.info(f"SDK GIF: playing {gif_name!r}, {len(packed)} frames")

    async def _gif_loop(self):
        """Cycle through GIF frames forever at their native durations."""
        idx = 0
        sent = 0
        while self.gif_active and self._gif_frames:
            arr, n = self._gif_frames[idx % len(self._gif_frames)]
            dur_ms = self._gif_durations_ms[idx % len(self._gif_durations_ms)]
            t0 = time.perf_counter()

            if self._dll and self._ready:
                try:
                    self._dll.ldbSendFrameToImage(
                        self._image_name, n,
                        ctypes.byref(arr), ctypes.byref(self._zone_arr),
                        SCAN_RATE,
                    )
                    sent += 1
                except Exception as e:
                    logger.error(f"SDK GIF: frame error: {e}")

            elapsed = time.perf_counter() - t0
            sleep_time = (dur_ms / 1000.0) - elapsed
            await asyncio.sleep(max(sleep_time, 0.001))
            idx += 1

        logger.info(f"SDK GIF: stopped after {sent} frames sent")

    async def stop_gif(self):
        """Stop GIF playback."""
        if not self.gif_active:
            return
        self.gif_active = False
        if self._gif_task:
            try:
                await asyncio.wait_for(self._gif_task, timeout=1.0)
            except asyncio.TimeoutError:
                self._gif_task.cancel()
            self._gif_task = None
        self._gif_frames = []
        self._gif_durations_ms = []
        self.current_gif_name = ""
        # Skip ldbBlackout — see note in stop_song. _send_loop resuming with
        # empty current_points is enough to stop output without bricking
        # subsequent frame sends.

    async def play_song(self, frames, audio_path, song_name=""):
        """Play a song — stream pre-generated LaserFrames synced to an audio file.

        frames: list of LaserFrame (has .points with LaserPoint objects and .timestamp_ms)
        audio_path: Path or str to audio file (wav)
        """
        # Stop anything currently playing (GIF, song, or points)
        await self.stop_song()
        await self.stop_gif()
        self.current_points = []

        if not frames:
            logger.warning("SDK SONG: no frames provided")
            return False

        if self._ready:
            # Rotate the zone image name so BEYOND always sees a fresh handle.
            # Keeping the same name across multiple song plays causes
            # ldbSendFrameToImage to start returning result=2 on the second
            # play (stale handle in BEYOND).
            try:
                if self._image_name:
                    self._dll.ldbDeleteZoneImage(self._image_name)
            except Exception:
                pass
            new_name = f"Babylon_{_uuid.uuid4().hex[:8]}".encode("ascii")
            self._image_name = new_name
            try:
                r = self._dll.ldbCreateZoneImage(0, self._image_name)
                self._dll.ldbEnableLaserOutput()
                logger.info(f"SDK SONG: new zone image {new_name.decode()} (CreateZoneImage={r})")
            except Exception as e:
                logger.warning(f"SDK SONG: new image failed: {e}")

        # Pre-pack all laser frames into ctypes arrays once up front
        packed = []
        timestamps = []
        for frame in frames:
            pts = frame.points
            n = min(len(pts), 8192)
            arr = (SdkPoint * n)()
            for i in range(n):
                p = pts[i]
                arr[i].x = float(p.x)
                arr[i].y = float(p.y)
                arr[i].z = 0.0
                if getattr(p, "blanked", False):
                    arr[i].color = 0
                else:
                    r = int(getattr(p, "r", 0)) & 0xFF
                    g = int(getattr(p, "g", 0)) & 0xFF
                    b = int(getattr(p, "b", 0)) & 0xFF
                    arr[i].color = r | (g << 8) | (b << 16)
                arr[i].rep_count = 0
                arr[i].focus = 0
                arr[i].status = 0
                arr[i].zero = 0
            packed.append((arr, n))
            timestamps.append(float(frame.timestamp_ms))

        # Load audio via soundfile (imported lazily to avoid optional deps at import time)
        import soundfile as sf
        audio_data, audio_sr = sf.read(str(audio_path), dtype="float32")

        self._song_frames_packed = packed
        self._song_timestamps_ms = timestamps
        self._song_audio_data = audio_data
        self._song_audio_sr = int(audio_sr)
        self._song_audio_position = 0
        self.current_song_name = song_name
        self.song_total_ms = timestamps[-1] + 33.33 if timestamps else 0.0
        self.song_frames_sent = 0
        self._song_stop_event = asyncio.Event()

        # Start audio via sounddevice
        import sounddevice as sd
        channels = 1 if audio_data.ndim == 1 else audio_data.shape[1]

        def _audio_callback(outdata, nframes, time_info, status):
            if self._song_audio_data is None:
                outdata.fill(0)
                return
            start = self._song_audio_position
            end = start + nframes
            if end > len(self._song_audio_data):
                remaining = len(self._song_audio_data) - start
                if remaining > 0:
                    outdata[:remaining] = self._song_audio_data[start:start + remaining].reshape(outdata[:remaining].shape)
                outdata[remaining:] = 0
                # Signal end via event loop
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(self._song_stop_event.set)
                except Exception:
                    pass
            else:
                outdata[:] = self._song_audio_data[start:end].reshape(outdata.shape)
            self._song_audio_position = end

        self._song_audio_stream = sd.OutputStream(
            samplerate=self._song_audio_sr,
            channels=channels,
            callback=_audio_callback,
            blocksize=1024,
        )
        self._song_audio_stream.start()

        self.song_active = True
        self._song_task = asyncio.create_task(self._song_loop())
        logger.info(f"SDK SONG: playing {song_name!r}, {len(packed)} frames, {self.song_total_ms/1000:.1f}s")
        return True

    def _find_song_frame_idx(self, time_ms: float) -> int:
        """Binary search for the last frame whose timestamp_ms <= time_ms."""
        ts = self._song_timestamps_ms
        if not ts:
            return -1
        lo, hi = 0, len(ts) - 1
        while lo < hi:
            mid = (lo + hi + 1) >> 1
            if ts[mid] <= time_ms:
                lo = mid
            else:
                hi = mid - 1
        return lo

    async def _song_loop(self):
        """Sync frames to audio clock, push to DLL from the event loop thread."""
        frame_interval = 1.0 / TARGET_FPS
        last_idx = -1
        try:
            while self.song_active:
                loop_start = time.perf_counter()

                # Compute current audio time and pick frame
                time_ms = (self._song_audio_position / self._song_audio_sr) * 1000.0
                idx = self._find_song_frame_idx(time_ms)

                if idx >= 0 and idx != last_idx and self._dll and self._ready:
                    arr, n = self._song_frames_packed[idx]
                    if n == 0:
                        # Skip empty frames — sending n=0 poisons the image handle
                        last_idx = idx
                        elapsed = time.perf_counter() - loop_start
                        await asyncio.sleep(max(frame_interval - elapsed, 0.001))
                        continue
                    try:
                        result = self._dll.ldbSendFrameToImage(
                            self._image_name, n,
                            ctypes.byref(arr), ctypes.byref(self._zone_arr),
                            SCAN_RATE,
                        )
                        self.song_frames_sent += 1
                        if self.song_frames_sent <= 3 or self.song_frames_sent % 60 == 0:
                            logger.info(
                                f"SDK SONG: frame #{self.song_frames_sent}, n={n}, result={result}, image={self._image_name}"
                            )
                        last_idx = idx
                    except Exception as e:
                        logger.error(f"SDK SONG: frame error: {e}")

                # Check stop signal from audio callback
                if self._song_stop_event and self._song_stop_event.is_set():
                    break

                elapsed = time.perf_counter() - loop_start
                await asyncio.sleep(max(frame_interval - elapsed, 0.001))
        except asyncio.CancelledError:
            pass
        finally:
            self.song_active = False
            logger.info(f"SDK SONG: stopped after {self.song_frames_sent} frames sent")

    async def stop_song(self):
        """Stop song playback."""
        if not self.song_active and self._song_audio_stream is None:
            return
        self.song_active = False
        if self._song_stop_event:
            self._song_stop_event.set()
        if self._song_task:
            try:
                await asyncio.wait_for(self._song_task, timeout=1.5)
            except asyncio.TimeoutError:
                self._song_task.cancel()
            self._song_task = None
        if self._song_audio_stream:
            try:
                self._song_audio_stream.stop()
                self._song_audio_stream.close()
            except Exception:
                pass
            self._song_audio_stream = None
        self._song_frames_packed = []
        self._song_timestamps_ms = []
        self._song_audio_data = None
        self._song_audio_position = 0
        self.current_song_name = ""
        # Deliberately no ldbBlackout here — calling it leaves the SDK in a
        # state where subsequent ldbSendFrameToImage returns result=2 until a
        # server restart. The _send_loop resumes with empty current_points,
        # which naturally stops laser output.

    def blackout(self):
        self.current_points = []
        self.current_pattern_name = ""
        if self.gif_active:
            self.gif_active = False
        if self.song_active:
            self.song_active = False
        if self._dll and self._ready:
            try:
                self._dll.ldbBlackout()
                logger.info("SDK: Blackout")
            except Exception as e:
                logger.error(f"SDK: Blackout error: {e}")

    def get_status(self):
        return {
            "initialized": self.initialized,
            "simulation_mode": self.simulation_mode,
            "streaming": len(self.current_points) > 0 or self.gif_active,
            "point_count": len(self.current_points),
            "current_pattern": self.current_pattern_name,
            "frames_sent": self.frames_sent,
            "fps": TARGET_FPS,
            "scan_rate": abs(SCAN_RATE),
            "last_error": self.last_error,
            "gif_active": self.gif_active,
            "current_gif": self.current_gif_name,
            "song_active": self.song_active,
            "current_song": self.current_song_name,
            "song_frames_sent": self.song_frames_sent,
            "song_total_ms": self.song_total_ms,
            "song_current_ms": (self._song_audio_position / self._song_audio_sr * 1000.0) if self._song_audio_sr else 0.0,
        }

    def shutdown(self):
        """Clean shutdown."""
        logger.info("SDK: Shutting down...")
        self.running = False
        if self._task:
            self._task.cancel()

        if self._dll and self._ready:
            try:
                if self._image_name:
                    self._dll.ldbDeleteZoneImage(self._image_name)
                    self._image_name = None
                self._dll.ldbDestroy()
                logger.info("SDK: Clean shutdown")
            except Exception as e:
                logger.error(f"SDK: Shutdown error: {e}")
        self._ready = False
