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
IMAGE_NAME = b"AgentOutput"
SCAN_RATE = -30000
TARGET_FPS = 30


def _clear_cues_sync():
    """Stop all existing cues via PangoScript TCP (blocking — run in executor)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(("localhost", 16063))
        sock.sendall(b"StopAllNow\r\n")
        try:
            resp = sock.recv(1024).decode("ascii", errors="replace").strip()
            logger.info(f"SDK: PangoScript StopAllNow -> {resp}")
        except socket.timeout:
            pass
        sock.close()
    except Exception as e:
        logger.warning(f"SDK: PangoScript clear skipped: {e}")


async def clear_cues_via_pangoscript():
    """Non-blocking wrapper — runs the socket call in a thread executor."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _clear_cues_sync)


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

        while self.running:
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

    async def set_points(self, points, pattern_name=""):
        """Swap the point list. Clear cues first so SDK output is visible."""
        if points and self._ready:
            await clear_cues_via_pangoscript()
        self.current_points = points
        self.current_pattern_name = pattern_name
        logger.info(f"SDK: Points updated — {len(points)} pts, pattern={pattern_name!r}")

    def blackout(self):
        self.current_points = []
        self.current_pattern_name = ""
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
            "streaming": len(self.current_points) > 0,
            "point_count": len(self.current_points),
            "current_pattern": self.current_pattern_name,
            "frames_sent": self.frames_sent,
            "fps": TARGET_FPS,
            "scan_rate": abs(SCAN_RATE),
            "last_error": self.last_error,
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
