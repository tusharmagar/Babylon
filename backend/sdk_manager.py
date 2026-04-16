"""
BEYOND SDK Manager — Loads BEYONDIOx64.dll via ctypes, manages a continuous 30fps
send loop on a background thread. The AI just swaps the point list and the laser
output updates instantly on the next frame.

One zone image ("AgentOutput") is created at startup and reused for the entire session.
"""

import ctypes
import threading
import time
import logging
import os

logger = logging.getLogger(__name__)

# ===== Point Structure (16 bytes) =====
class SdkPoint(ctypes.Structure):
    _fields_ = [
        ('x', ctypes.c_float),       # -32768 to +32767
        ('y', ctypes.c_float),       # -32768 to +32767
        ('z', ctypes.c_float),       # Usually 0
        ('color', ctypes.c_uint32),  # R | (G<<8) | (B<<16), 0 = blanked
        ('rep_count', ctypes.c_uint8),  # Corner dwell (0=normal, 2-3=sharp)
        ('focus', ctypes.c_uint8),   # Reserved, always 0
        ('status', ctypes.c_uint8),  # Reserved, always 0
        ('zero', ctypes.c_uint8),    # Must be 0
    ]


# Default DLL path — hardcoded for hackathon
DLL_PATH = r"C:\Program Files\MadMapper 5.7.1\BEYONDIOx64.dll"
IMAGE_NAME = b"AgentOutput"
SCAN_RATE = -30000  # Negative = absolute Hz (30,000 pps)
TARGET_FPS = 30


class BeyondSDKManager:
    """
    Manages the BEYOND SDK DLL lifecycle and a continuous frame-sending loop.

    Usage:
        manager = BeyondSDKManager()
        manager.initialize()       # Load DLL, wait for BEYOND, create zone image
        manager.set_points([...])  # Swap point data (instant on next frame)
        manager.blackout()         # Clear laser
        manager.shutdown()         # Clean up
    """

    def __init__(self):
        self.dll = None
        self.initialized = False
        self.simulation_mode = False  # True when DLL not available
        self.current_points = []
        self.current_pattern_name = ""
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.frames_sent = 0
        self.last_error = None

    def initialize(self):
        """Load DLL, initialize, wait for BEYOND, create zone image, start send loop."""
        try:
            if not os.path.exists(DLL_PATH):
                logger.warning(f"BEYOND DLL not found at {DLL_PATH} — running in simulation mode")
                self.simulation_mode = True
                self.initialized = True
                self._start_send_loop()
                return True

            self.dll = ctypes.CDLL(DLL_PATH)

            # Set up function signatures
            self.dll.ldbCreate.restype = ctypes.c_int
            self.dll.ldbBeyondExeReady.restype = ctypes.c_int
            self.dll.ldbBeyondExeStarted.restype = ctypes.c_int
            self.dll.ldbCreateZoneImage.argtypes = [ctypes.c_int, ctypes.c_char_p]
            self.dll.ldbCreateZoneImage.restype = ctypes.c_int
            self.dll.ldbDeleteZoneImage.argtypes = [ctypes.c_char_p]
            self.dll.ldbSendFrameToImage.argtypes = [
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            self.dll.ldbSendFrameToImage.restype = ctypes.c_int
            self.dll.ldbEnableLaserOutput.restype = ctypes.c_int
            self.dll.ldbBlackout.restype = ctypes.c_int
            self.dll.ldbDestroy.restype = ctypes.c_int

            # Step 1: Initialize DLL
            self.dll.ldbCreate()
            logger.info("SDK: ldbCreate() called")

            # Step 2: Wait for BEYOND to be ready (timeout after 10s)
            timeout = 10
            start = time.time()
            while not self.dll.ldbBeyondExeReady():
                if time.time() - start > timeout:
                    logger.error("SDK: BEYOND not ready after 10s timeout")
                    self.last_error = "BEYOND not ready — is it running?"
                    self.simulation_mode = True
                    self.initialized = True
                    self._start_send_loop()
                    return True
                time.sleep(0.5)

            logger.info("SDK: BEYOND is ready")

            # Step 3: Create one zone image for the whole session
            result = self.dll.ldbCreateZoneImage(0, IMAGE_NAME)
            logger.info(f"SDK: ldbCreateZoneImage → {result}")

            # Step 4: Enable laser output
            self.dll.ldbEnableLaserOutput()
            logger.info("SDK: Laser output enabled")

            self.initialized = True
            self.simulation_mode = False

            # Step 5: Start continuous send loop
            self._start_send_loop()

            logger.info("SDK: Fully initialized, send loop running at 30fps")
            return True

        except OSError as e:
            logger.warning(f"SDK: Could not load DLL ({e}) — simulation mode")
            self.simulation_mode = True
            self.initialized = True
            self._start_send_loop()
            return True
        except Exception as e:
            logger.error(f"SDK: Initialization failed: {e}")
            self.last_error = str(e)
            self.simulation_mode = True
            self.initialized = True
            self._start_send_loop()
            return True

    def _start_send_loop(self):
        """Start the background 30fps frame-sending thread."""
        self.running = True
        self.thread = threading.Thread(target=self._send_loop, daemon=True)
        self.thread.start()
        logger.info(f"SDK: Send loop started (simulation={self.simulation_mode})")

    def _send_loop(self):
        """Continuous loop — sends whatever is in current_points at 30fps."""
        frame_time = 1.0 / TARGET_FPS

        while self.running:
            loop_start = time.time()

            with self.lock:
                points = self.current_points

            if points and not self.simulation_mode and self.dll:
                try:
                    count = min(len(points), 8192)  # SDK max
                    PointArray = SdkPoint * count
                    arr = PointArray()

                    for i in range(count):
                        p = points[i]
                        arr[i].x = float(p.get('x', 0))
                        arr[i].y = float(p.get('y', 0))
                        arr[i].z = 0.0
                        # Parse color: could be int, hex string, or 0
                        color = p.get('color', 0)
                        if isinstance(color, str):
                            color = int(color, 16) if color.startswith('0x') else int(color)
                        arr[i].color = ctypes.c_uint32(color)
                        arr[i].rep_count = int(p.get('rep_count', 0))
                        arr[i].focus = 0
                        arr[i].status = 0
                        arr[i].zero = 0

                    # Zone array: 256 bytes, first byte = 1 (zone 1, 1-based)
                    zone_arr = (ctypes.c_uint8 * 256)()
                    zone_arr[0] = 1

                    self.dll.ldbSendFrameToImage(
                        IMAGE_NAME,
                        count,
                        ctypes.byref(arr),
                        ctypes.byref(zone_arr),
                        SCAN_RATE,
                    )
                    self.frames_sent += 1

                except Exception as e:
                    if self.frames_sent % 300 == 0:  # Log every ~10s
                        logger.error(f"SDK: Frame send error: {e}")
            elif points and self.simulation_mode:
                # In simulation mode, just count frames
                self.frames_sent += 1

            # Sleep to maintain target FPS
            elapsed = time.time() - loop_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def set_points(self, points, pattern_name=""):
        """
        Swap the current point list. Thread-safe — the send loop picks up
        the new points on the very next frame.
        """
        with self.lock:
            self.current_points = points
            self.current_pattern_name = pattern_name
        logger.info(f"SDK: Points updated — {len(points)} points, pattern='{pattern_name}'")

    def blackout(self):
        """Clear everything from the laser."""
        with self.lock:
            self.current_points = []
            self.current_pattern_name = ""
        if self.dll and not self.simulation_mode:
            try:
                self.dll.ldbBlackout()
                logger.info("SDK: Blackout sent")
            except Exception as e:
                logger.error(f"SDK: Blackout error: {e}")

    def get_status(self):
        """Get current SDK status."""
        with self.lock:
            point_count = len(self.current_points)
            pattern = self.current_pattern_name
        return {
            "initialized": self.initialized,
            "simulation_mode": self.simulation_mode,
            "streaming": point_count > 0,
            "point_count": point_count,
            "current_pattern": pattern,
            "frames_sent": self.frames_sent,
            "fps": TARGET_FPS,
            "scan_rate": abs(SCAN_RATE),
            "last_error": self.last_error,
        }

    def shutdown(self):
        """Clean shutdown — stop loop, delete image, destroy DLL."""
        logger.info("SDK: Shutting down...")
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

        if self.dll and not self.simulation_mode:
            try:
                self.dll.ldbBlackout()
                self.dll.ldbDeleteZoneImage(IMAGE_NAME)
                self.dll.ldbDestroy()
                logger.info("SDK: Clean shutdown complete")
            except Exception as e:
                logger.error(f"SDK: Shutdown error: {e}")
