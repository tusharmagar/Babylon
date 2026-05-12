"""Per-frame stroke-art centerline extraction for videos.

Mirrors the SAM cache pattern: pre-process the whole video once into a
per-frame JSON cache that the visualizer reads back during playback.

Cache layout:
    backend/stroke_video_cache/<cache_id>/
        manifest.json               # status, fps, n_frames, processed, etc.
        frames/000000.json          # { polylines: [...] }
        frames/000001.json
        ...

Default: skeleton method only. The other methods are 5–15× slower per frame
and we ship them via the still-image endpoint instead.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(__file__).resolve().parent.parent / "stroke_video_cache"
CACHE_ROOT.mkdir(exist_ok=True)


@dataclass
class StrokeVideoJob:
    cache_id: str
    video_path: str
    method: str               # currently "skeleton" or "neon"
    stride: int               # process every Nth frame
    target_width: int         # downscale wider videos to this width before processing
    brightness_threshold: int
    morph_close: int
    min_length: int
    simplify_eps: float
    prune_branches: int
    n_colors: int             # only used if method == 'per_color'
    max_frames: Optional[int]
    sam_cache_id: Optional[str] = None  # gate each frame by the SAM mask if set


def _cache_key(job_dict: dict) -> str:
    payload = json.dumps(job_dict, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def cache_dir_for(cache_id: str) -> Path:
    return CACHE_ROOT / cache_id


def write_manifest(cache_id: str, manifest: dict) -> None:
    d = cache_dir_for(cache_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))


def read_manifest(cache_id: str) -> Optional[dict]:
    f = cache_dir_for(cache_id) / "manifest.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def plan_job(
    *,
    video_path: str,
    method: str = "skeleton",
    stride: int = 2,
    target_width: int = 480,
    brightness_threshold: int = 90,
    morph_close: int = 3,
    min_length: int = 12,
    simplify_eps: float = 1.5,
    prune_branches: int = 8,
    n_colors: int = 5,
    max_frames: Optional[int] = None,
    sam_cache_id: Optional[str] = None,
) -> StrokeVideoJob:
    p = Path(video_path).expanduser().resolve()
    try:
        mtime = int(p.stat().st_mtime)
    except FileNotFoundError:
        mtime = 0
    cache_id = _cache_key({
        "path": str(p), "mtime": mtime,
        "method": method, "stride": int(stride), "target_width": int(target_width),
        "brightness_threshold": int(brightness_threshold), "morph_close": int(morph_close),
        "min_length": int(min_length), "simplify_eps": float(simplify_eps),
        "prune_branches": int(prune_branches), "n_colors": int(n_colors),
        "sam_cache_id": sam_cache_id or "",
    })
    return StrokeVideoJob(
        cache_id=cache_id,
        video_path=str(p),
        method=method,
        stride=int(stride),
        target_width=int(target_width),
        brightness_threshold=int(brightness_threshold),
        morph_close=int(morph_close),
        min_length=int(min_length),
        simplify_eps=float(simplify_eps),
        prune_branches=int(prune_branches),
        n_colors=int(n_colors),
        max_frames=max_frames,
        sam_cache_id=sam_cache_id,
    )


def _process_frame_skeleton(frame_bgr, *, brightness_threshold, morph_close,
                            min_length, simplify_eps, prune_branches):
    """Inline a skeleton centerline pass (avoid disk I/O of the still-image fn)."""
    import cv2
    import numpy as np
    from services.stroke_centerlines import (
        _brightness_mask, _skeletonize, _prune_skeleton,
        _trace_skeleton, _color_at, _simplify_polylines,
    )
    mask = _brightness_mask(frame_bgr, brightness_threshold, morph_close)
    sk = _skeletonize(mask)
    sk = _prune_skeleton(sk, prune_branches)
    polylines = _trace_skeleton(sk, lambda x, y: _color_at(frame_bgr, x, y), min_length=min_length)
    return _simplify_polylines(polylines, simplify_eps)


def _process_frame_neon(frame_bgr, *, min_length, simplify_eps, prune_branches):
    import cv2
    import numpy as np
    from skimage.filters import meijering
    from services.stroke_centerlines import (
        _skeletonize, _prune_skeleton,
        _trace_skeleton, _color_at, _simplify_polylines,
    )
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2].astype(np.float32) / 255.0
    response = meijering(v, sigmas=[1.0, 2.0, 4.0], black_ridges=False)
    mask = response > 0.04
    sk = _skeletonize(mask)
    sk = _prune_skeleton(sk, prune_branches)
    polylines = _trace_skeleton(sk, lambda x, y: _color_at(frame_bgr, x, y), min_length=min_length)
    return _simplify_polylines(polylines, simplify_eps)


def run_job(job: StrokeVideoJob) -> dict:
    """Process the whole video, write per-frame JSONs, update manifest as we go."""
    import cv2

    cache = cache_dir_for(job.cache_id)
    cache.mkdir(parents=True, exist_ok=True)
    frames_dir = cache / "frames"
    frames_dir.mkdir(exist_ok=True)

    cap = cv2.VideoCapture(job.video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {job.video_path}")
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    scale = min(1.0, job.target_width / max(src_w, 1))
    proc_w = int(round(src_w * scale))
    proc_h = int(round(src_h * scale))

    manifest = {
        "cache_id": job.cache_id,
        "status": "running",
        "started_at": time.time(),
        "video_path": job.video_path,
        "method": job.method,
        "stride": job.stride,
        "target_width": job.target_width,
        "src_width": src_w, "src_height": src_h,
        "proc_width": proc_w, "proc_height": proc_h,
        "fps": fps,
        "n_frames": n_frames,
        "processed_frames": 0,
        "total_polylines": 0,
        "progress": 0.0,
        "error": None,
        "params": {
            "brightness_threshold": job.brightness_threshold,
            "morph_close": job.morph_close,
            "min_length": job.min_length,
            "simplify_eps": job.simplify_eps,
            "prune_branches": job.prune_branches,
        },
    }
    write_manifest(job.cache_id, manifest)

    try:
        i = 0
        produced = 0
        total_pls = 0
        last_save = time.time()
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            if job.max_frames is not None and i >= job.max_frames:
                break
            if i % job.stride != 0:
                i += 1
                continue
            if scale < 1.0:
                frame_bgr = cv2.resize(frame_bgr, (proc_w, proc_h), interpolation=cv2.INTER_AREA)

            # Gate the frame by the SAM mask for this frame index, if requested.
            if job.sam_cache_id:
                from services.stroke_centerlines import _apply_sam_mask
                frame_bgr = _apply_sam_mask(frame_bgr, job.sam_cache_id, i)

            try:
                if job.method == "neon":
                    polys = _process_frame_neon(
                        frame_bgr,
                        min_length=job.min_length,
                        simplify_eps=job.simplify_eps,
                        prune_branches=job.prune_branches,
                    )
                else:
                    polys = _process_frame_skeleton(
                        frame_bgr,
                        brightness_threshold=job.brightness_threshold,
                        morph_close=job.morph_close,
                        min_length=job.min_length,
                        simplify_eps=job.simplify_eps,
                        prune_branches=job.prune_branches,
                    )
            except Exception as e:
                logger.warning("frame %d failed: %s", i, e)
                polys = []

            (frames_dir / f"{i:06d}.json").write_text(json.dumps({
                "frame_index": i,
                "polylines": polys,
                "n_paths": len(polys),
                "n_points": sum(len(p["points"]) for p in polys),
            }))
            produced += 1
            total_pls += len(polys)

            now = time.time()
            if now - last_save > 0.5:
                manifest["processed_frames"] = produced
                manifest["total_polylines"] = total_pls
                manifest["progress"] = (i + 1) / max(n_frames, 1)
                write_manifest(job.cache_id, manifest)
                last_save = now

            i += 1

        cap.release()
        manifest["status"] = "done"
        manifest["progress"] = 1.0
        manifest["processed_frames"] = produced
        manifest["total_polylines"] = total_pls
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        return manifest

    except Exception as e:
        cap.release()
        logger.exception("stroke-video job failed")
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        manifest["traceback"] = traceback.format_exc()
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        raise
