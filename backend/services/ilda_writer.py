"""Stage 9: ILDA Format 5 Binary Writer.

Writes LaserFrames to an .ild file in ILDA Format 5
(2D coordinates with true color RGB).
"""
import struct
import logging
from pathlib import Path
from typing import List
from models.laser_types import LaserFrame, LaserPoint

logger = logging.getLogger(__name__)


def write_ilda_file(frames: List[LaserFrame], output_path: Path) -> int:
    """Write frames to an ILDA Format 5 binary file.
    
    Returns file size in bytes.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    total_frames = len(frames)
    
    logger.info(f"Writing ILDA file: {total_frames} frames to {output_path}")
    
    with open(output_path, 'wb') as f:
        for frame_idx, frame in enumerate(frames):
            points = frame.points
            num_points = len(points)
            
            if num_points == 0:
                continue
            
            # Write frame header (32 bytes)
            header = _build_header(
                frame_num=frame_idx,
                total_frames=total_frames,
                num_points=num_points,
                frame_name=f"Frame{frame_idx:03d}"
            )
            f.write(header)
            
            # Write point records
            for pt_idx, point in enumerate(points):
                is_last = (pt_idx == num_points - 1)
                record = _build_point_record(point, is_last)
                f.write(record)
        
        # Write closing header (point_count = 0)
        closing = _build_header(
            frame_num=total_frames,
            total_frames=total_frames,
            num_points=0,
            frame_name="EndOfFil"
        )
        f.write(closing)
    
    file_size = output_path.stat().st_size
    logger.info(f"ILDA file written: {file_size} bytes ({file_size/1024:.1f} KB)")
    return file_size


def _build_header(
    frame_num: int,
    total_frames: int,
    num_points: int,
    frame_name: str = "Frame000"
) -> bytes:
    """Build a 32-byte ILDA frame header.
    
    All multi-byte values are BIG-ENDIAN.
    
    Offset  Size  Field
    0       4     "ILDA" signature
    4       3     Reserved (0x00)
    7       1     Format code (5)
    8       8     Frame name (ASCII, null-padded)
    16      8     Company name ("Babylon\\0", null-padded)
    24      2     Point count (uint16 BE)
    26      2     Frame number (uint16 BE)
    28      2     Total frames (uint16 BE)
    30      1     Scanner head (0)
    31      1     Reserved (0)
    """
    # Pad/truncate name to 8 bytes
    name_bytes = frame_name.encode('ascii')[:8].ljust(8, b'\x00')
    company_bytes = b'Babylon\x00'
    
    # Clamp values to uint16 range
    num_points = min(65535, max(0, num_points))
    frame_num = min(65535, max(0, frame_num))
    total_frames = min(65535, max(0, total_frames))
    
    header = struct.pack('>4s3xB',
        b'ILDA',      # Signature
        5,            # Format code
    )
    header += name_bytes      # Frame name (8 bytes)
    header += company_bytes   # Company name (8 bytes)
    header += struct.pack('>HHH',
        num_points,   # Point count
        frame_num,    # Frame number
        total_frames, # Total frames
    )
    header += struct.pack('BB', 0, 0)  # Scanner head + reserved
    
    return header


def _build_point_record(point: LaserPoint, is_last: bool = False) -> bytes:
    """Build an 8-byte ILDA Format 5 point record.
    
    Offset  Size  Field        Encoding
    0       2     X            int16 big-endian
    2       2     Y            int16 big-endian
    4       1     Status byte  bit6=blank, bit7=last
    5       1     Blue         uint8
    6       1     Green        uint8
    7       1     Red          uint8
    """
    # Clamp coordinates
    x = max(-32768, min(32767, int(point.x)))
    y = max(-32768, min(32767, int(point.y)))
    
    # Status byte
    status = 0
    if point.blanked:
        status |= 0x40  # Bit 6: blanking flag
    if is_last:
        status |= 0x80  # Bit 7: last point flag
    
    # Clamp colors
    r = max(0, min(255, int(point.r)))
    g = max(0, min(255, int(point.g)))
    b = max(0, min(255, int(point.b)))
    
    return struct.pack('>hhBBBB', x, y, status, b, g, r)
