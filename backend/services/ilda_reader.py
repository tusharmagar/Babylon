"""
ILDA Format 5 binary file reader.
Parses .ild files back into frame objects for streaming playback.
"""

from __future__ import annotations

import struct
from pathlib import Path
from models.laser_types import LaserFrame, LaserPoint

HEADER_SIZE = 32
POINT_SIZE_FORMAT5 = 8


def read_ilda_file(file_path: Path) -> list[LaserFrame]:
    """
    Parse an ILDA Format 5 file into a list of LaserFrame objects.
    Each frame gets a timestamp based on 30fps playback.
    """
    frames = []
    fps = 30.0

    with open(file_path, "rb") as f:
        data = f.read()

    offset = 0
    while offset + HEADER_SIZE <= len(data):
        # Read 32-byte header
        sig = data[offset : offset + 4]
        if sig != b"ILDA":
            break

        format_code = data[offset + 7]
        point_count = struct.unpack(">H", data[offset + 24 : offset + 26])[0]

        # Null header = end of file
        if point_count == 0:
            break

        # Only handle Format 5 (2D + True Color)
        if format_code != 5:
            # Skip unsupported formats
            offset += HEADER_SIZE + point_count * 8
            continue

        data_start = offset + HEADER_SIZE
        data_end = data_start + point_count * POINT_SIZE_FORMAT5

        if data_end > len(data):
            break

        points = []
        for i in range(point_count):
            p_offset = data_start + i * POINT_SIZE_FORMAT5
            x, y = struct.unpack(">hh", data[p_offset : p_offset + 4])
            status = data[p_offset + 4]
            blue = data[p_offset + 5]
            green = data[p_offset + 6]
            red = data[p_offset + 7]

            blanked = (status & 0x40) != 0

            points.append(LaserPoint(
                x=x, y=y, r=red, g=green, b=blue, blanked=blanked,
            ))

        frame_index = len(frames)
        timestamp_ms = (frame_index / fps) * 1000.0
        frames.append(LaserFrame(timestamp_ms=timestamp_ms, points=points))

        offset = data_end

    return frames


def pad_frame_points(points: list[LaserPoint], target_count: int) -> list[LaserPoint]:
    """
    Pad a frame's points to fill the scan rate budget.
    Repeats the frame's points to reach target_count.
    This prevents flicker by keeping the galvos busy.
    """
    if not points or target_count <= 0:
        return points

    if len(points) >= target_count:
        return points[:target_count]

    # Repeat the frame's points to fill the budget
    padded = []
    while len(padded) < target_count:
        padded.extend(points)
    return padded[:target_count]
