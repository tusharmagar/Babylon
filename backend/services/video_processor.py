"""Video → laser vectorization with color preservation.

Downloads a YouTube video with audio, trims to a requested duration, then
vectorizes each frame. Colors are recovered by k-means clustering each frame
into K dominant colors and tracing contours per cluster separately.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import yt_dlp

from models.laser_types import LaserFrame, LaserPoint

logger = logging.getLogger(__name__)

LASER_RANGE = 14000
DEFAULT_MAX_POINTS = 800
DEFAULT_COLOR_CLUSTERS = 5
LINE_BRIGHTNESS_THRESHOLD = 30  # min grayscale value to consider "on"


def download_video_with_audio(
    url: str, out_dir: Path, duration_s: float = 45.0
) -> Tuple[Path, Path, dict]:
    """Download a YouTube video and split into trimmed mp4 and wav audio.

    Returns (video_mp4_path, audio_wav_path, info_dict).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_template = str(out_dir / "raw.%(ext)s")
    trimmed_video = out_dir / "video.mp4"
    trimmed_audio = out_dir / "audio.wav"

    ydl_opts = {
        "format": "best[ext=mp4][height<=720]/best[height<=720]/best",
        "outtmpl": raw_template,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    logger.info(f"yt-dlp: downloading {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Find whatever yt-dlp actually wrote
    candidates = sorted(out_dir.glob("raw.*"))
    if not candidates:
        raise RuntimeError("Video download failed — no output file")
    raw_path = candidates[0]
    logger.info(f"yt-dlp: downloaded {raw_path.name} ({raw_path.stat().st_size // 1024} KB)")

    # Trim first N seconds of video (re-encode so we always start at t=0 cleanly)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", str(raw_path), "-t", str(duration_s),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         str(trimmed_video)],
        check=True, capture_output=True,
    )
    # Extract first N seconds of audio as WAV mono 44.1k
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", str(raw_path), "-t", str(duration_s),
         "-vn", "-ac", "1", "-ar", "44100", str(trimmed_audio)],
        check=True, capture_output=True,
    )

    return trimmed_video, trimmed_audio, info


def _frame_to_line_points(
    bgr_frame: np.ndarray,
    max_points: int,
) -> List[LaserPoint]:
    """Column-scan vectorizer for waveform / line-drawing videos.

    For each x-column, find the brightness-weighted y centroid of the
    colored line and sample the pixel's actual color. Yields a smooth,
    ordered polyline with ~max_points samples across the frame width.
    """
    h, w = bgr_frame.shape[:2]
    gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)

    # Binary mask of "bright enough" pixels
    mask = gray > LINE_BRIGHTNESS_THRESHOLD
    col_has_line = mask.any(axis=0)

    active_xs = np.where(col_has_line)[0]
    if len(active_xs) == 0:
        return []

    # Pick a stride to hit ~max_points across the active columns
    if len(active_xs) > max_points:
        pick = np.linspace(0, len(active_xs) - 1, max_points).astype(int)
        sampled_xs = active_xs[pick]
    else:
        sampled_xs = active_xs

    # Brightness-weighted centroid y for each sampled column
    ys = np.zeros(len(sampled_xs), dtype=np.int32)
    colors = np.zeros((len(sampled_xs), 3), dtype=np.int32)  # BGR
    for i, x in enumerate(sampled_xs):
        col_mask = mask[:, x]
        col_ys = np.where(col_mask)[0]
        weights = gray[col_ys, x].astype(np.float32) + 1.0
        y_centroid = int(np.average(col_ys, weights=weights))
        ys[i] = y_centroid
        # Average the color in a small vertical window around the centroid
        y0 = max(0, y_centroid - 1)
        y1 = min(h, y_centroid + 2)
        colors[i] = bgr_frame[y0:y1, x].mean(axis=0).astype(int)

    scale = min(2 * LASER_RANGE / w, 2 * LASER_RANGE / h)
    laser_pts: List[LaserPoint] = []
    for i in range(len(sampled_xs)):
        x = int(sampled_xs[i])
        y = int(ys[i])
        lx = int((x - w / 2) * scale)
        ly = int(-(y - h / 2) * scale)
        b_val, g_val, r_val = int(colors[i, 0]), int(colors[i, 1]), int(colors[i, 2])
        laser_pts.append(LaserPoint(x=lx, y=ly, r=r_val, g=g_val, b=b_val))

    return laser_pts


def vectorize_video(
    video_path: Path,
    max_points: int = DEFAULT_MAX_POINTS,
    k_colors: int = DEFAULT_COLOR_CLUSTERS,  # kept for API compat; unused here
) -> List[LaserFrame]:
    """Read a video file, vectorize every frame using a column-scan line tracer.
    Timestamps use the source fps so audio and video stay synced."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval_ms = 1000.0 / src_fps

    frames: List[LaserFrame] = []
    idx = 0
    last_pts: List[LaserPoint] = []
    while True:
        ret, bgr = cap.read()
        if not ret:
            break
        pts = _frame_to_line_points(bgr, max_points=max_points)
        if not pts:
            pts = last_pts
        else:
            last_pts = pts
        # Skip leading empty frames — sending n=0 to the SDK poisons the image
        if pts or frames:
            frames.append(LaserFrame(points=pts, timestamp_ms=idx * frame_interval_ms))
        idx += 1

    cap.release()
    if frames:
        avg = sum(len(f.points) for f in frames) / len(frames)
        logger.info(
            f"Video: {len(frames)} frames @ {src_fps:.1f}fps, avg {avg:.0f} pts/frame"
        )
    return frames
