"""
BEYOND SDK wrapper using BEYONDIOx64.dll.

Pushes laser frames directly into BEYOND's rendering pipeline
via the SDK Image mechanism. No PangoScript TCP needed.
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path
from models.laser_types import LaserPoint


class SdkPoint(ctypes.Structure):
    """Maps to TSdkImagePoint (16 bytes)."""
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float),
        ("color", ctypes.c_uint32),
        ("rep_count", ctypes.c_uint8),
        ("focus", ctypes.c_uint8),
        ("status", ctypes.c_uint8),
        ("zero", ctypes.c_uint8),
    ]


# Default DLL path (shipped with MadMapper)
DEFAULT_DLL_PATH = r"C:\Program Files\MadMapper 5.7.1\BEYONDIOx64.dll"


def _pack_color(r: int, g: int, b: int) -> int:
    """Pack RGB into Windows BGR uint32: R | (G << 8) | (B << 16)."""
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


class BeyondSDK:
    """Manages the BEYOND SDK DLL lifecycle and frame pushing."""

    def __init__(self, dll_path: str = DEFAULT_DLL_PATH):
        self.dll_path = dll_path
        self._dll = None
        self._image_name: bytes | None = None
        self._ready = False
        self._zone_arr = (ctypes.c_ubyte * 256)()
        self._zone_arr[0] = 1  # Zone 1 (1-based)

    @property
    def ready(self) -> bool:
        return self._ready

    def connect(self) -> bool:
        """Load the DLL and initialize the SDK."""
        try:
            self._dll = ctypes.CDLL(self.dll_path)
            self._setup_argtypes()

            self._dll.ldbCreate()

            # Wait up to 5 seconds for BEYOND
            for _ in range(50):
                if self._dll.ldbBeyondExeReady():
                    break
                time.sleep(0.1)

            if not self._dll.ldbBeyondExeReady():
                return False

            self._ready = True
            return True
        except Exception:
            self._ready = False
            return False

    def _setup_argtypes(self):
        self._dll.ldbCreateZoneImage.argtypes = [ctypes.c_int, ctypes.c_char_p]
        self._dll.ldbCreateZoneImage.restype = ctypes.c_int
        self._dll.ldbDeleteZoneImage.argtypes = [ctypes.c_char_p]
        self._dll.ldbSendFrameToImage.argtypes = [
            ctypes.c_char_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
        ]
        self._dll.ldbSendFrameToImage.restype = ctypes.c_int
        self._dll.ldbEnableLaserOutput.restype = ctypes.c_int
        self._dll.ldbCreateProjectorImage.argtypes = [ctypes.c_int, ctypes.c_char_p]

    def create_image(self, name: str = "BabylonStream") -> bool:
        """Create an SDK Image buffer in zone 0."""
        if not self._ready:
            return False
        self._image_name = name.encode("ascii")
        self._dll.ldbCreateZoneImage(0, self._image_name)
        self._dll.ldbEnableLaserOutput()
        return True

    def send_frame(self, points: list[LaserPoint], scan_rate: int = 30000) -> bool:
        """Convert LaserPoints and push one frame to BEYOND."""
        if not self._ready or not self._image_name:
            return False

        n = min(len(points), 8192)
        if n == 0:
            return True

        arr = (SdkPoint * n)()
        for i in range(n):
            p = points[i]
            arr[i].x = float(p.x)
            arr[i].y = float(p.y)
            arr[i].z = 0.0
            if p.blanked:
                arr[i].color = 0
            else:
                arr[i].color = _pack_color(p.r, p.g, p.b)
            arr[i].rep_count = 0
            arr[i].focus = 0
            arr[i].status = 0
            arr[i].zero = 0

        result = self._dll.ldbSendFrameToImage(
            self._image_name, n,
            ctypes.byref(arr), ctypes.byref(self._zone_arr),
            -scan_rate,
        )
        return result == 1

    def blackout(self):
        """Kill all output."""
        if self._dll and self._ready:
            self._dll.ldbBlackout()

    def delete_image(self):
        """Remove the SDK Image buffer."""
        if self._dll and self._image_name:
            self._dll.ldbDeleteZoneImage(self._image_name)
            self._image_name = None

    def disconnect(self):
        """Clean up everything."""
        self.delete_image()
        if self._dll:
            try:
                self._dll.ldbDestroy()
            except Exception:
                pass
        self._ready = False

    def get_status(self) -> dict:
        if not self._dll or not self._ready:
            return {"connected": False, "projectors": 0, "zones": 0}
        return {
            "connected": True,
            "beyond_version": self._dll.ldbGetBeyondVersion(),
            "projectors": self._dll.ldbGetProjectorCount(),
            "zones": self._dll.ldbGetZoneCount(),
            "image_active": self._image_name is not None,
        }
