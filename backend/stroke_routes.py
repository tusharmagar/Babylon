"""HTTP routes for stroke-art centerline extraction (the three brainstorm methods)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import threading
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from services import stroke_centerlines, stroke_video

logger = logging.getLogger(__name__)
stroke_router = APIRouter(prefix="/api/stroke", tags=["stroke"])


class StrokeProcessRequest(BaseModel):
    path: str
    methods: List[str] = Field(
        default_factory=lambda: ["skeleton", "per_color", "potrace", "neon"],
        description='Subset of ["skeleton", "per_color", "potrace", "neon"]',
    )
    n_colors: int = 5
    brightness_threshold: int = 90
    morph_close: int = 3
    min_length: int = 12
    simplify_eps: float = 1.5
    prune_branches: int = 8
    sam_cache_id: Optional[str] = None        # if set, mask source by SAM region first
    sam_frame_idx: int = 0                    # for video SAM caches; image SAM uses 0


class MethodResult(BaseModel):
    polylines: Optional[List[dict]] = None
    error: Optional[str] = None
    elapsed_ms: Optional[float] = None


@stroke_router.post("/process")
def process(req: StrokeProcessRequest):
    src = Path(req.path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {src}")

    import time
    import cv2

    img = cv2.imread(str(src))
    if img is None:
        # Try PIL fallback to at least get dims
        try:
            from PIL import Image
            with Image.open(str(src)) as pim:
                w, h = pim.size
        except Exception:
            raise HTTPException(status_code=400, detail=f"could not decode image: {src}")
    else:
        h, w = img.shape[:2]

    out: dict = {"width": int(w), "height": int(h), "methods": {}}

    def run(name: str, fn, **kwargs):
        if name not in req.methods:
            return
        t0 = time.time()
        try:
            polys = fn(str(src), **kwargs)
            out["methods"][name] = {
                "polylines": polys,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "n_paths": len(polys),
                "n_points": sum(len(p["points"]) for p in polys),
            }
        except Exception as e:
            logger.exception("%s failed", name)
            out["methods"][name] = {"error": f"{type(e).__name__}: {e}",
                                     "elapsed_ms": int((time.time() - t0) * 1000)}

    common = dict(
        brightness_threshold=req.brightness_threshold,
        morph_close=req.morph_close,
        simplify_eps=req.simplify_eps,
        sam_cache_id=req.sam_cache_id,
        sam_frame_idx=req.sam_frame_idx,
    )

    run("skeleton",  stroke_centerlines.skeletonize_polylines,
        min_length=req.min_length, prune_branches=req.prune_branches, **common)
    run("per_color", stroke_centerlines.per_color_polylines,
        n_colors=req.n_colors, min_length=req.min_length,
        prune_branches=req.prune_branches, **common)
    run("potrace",   stroke_centerlines.potrace_polylines,
        n_colors=req.n_colors, **common)
    run("neon",      stroke_centerlines.neon_centerline_polylines,
        min_length=req.min_length, prune_branches=req.prune_branches,
        simplify_eps=req.simplify_eps,
        sam_cache_id=req.sam_cache_id, sam_frame_idx=req.sam_frame_idx)

    return out


# ---------- video pipeline ----------

class StrokeVideoRequest(BaseModel):
    path: str
    method: str = Field(default="skeleton", pattern="^(skeleton|neon)$")
    stride: int = 2
    target_width: int = 480
    brightness_threshold: int = 90
    morph_close: int = 3
    min_length: int = 12
    simplify_eps: float = 1.5
    prune_branches: int = 8
    n_colors: int = 5
    max_frames: Optional[int] = None
    sam_cache_id: Optional[str] = None


_running_jobs_lock = threading.Lock()
_running_jobs: set = set()


def _run_stroke_video(job: stroke_video.StrokeVideoJob):
    cid = job.cache_id
    with _running_jobs_lock:
        if cid in _running_jobs:
            return
        _running_jobs.add(cid)
    try:
        stroke_video.run_job(job)
    finally:
        with _running_jobs_lock:
            _running_jobs.discard(cid)


@stroke_router.post("/process-video")
def process_video(req: StrokeVideoRequest, background: BackgroundTasks):
    src = Path(req.path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {src}")
    job = stroke_video.plan_job(
        video_path=str(src),
        method=req.method,
        stride=req.stride,
        target_width=req.target_width,
        brightness_threshold=req.brightness_threshold,
        morph_close=req.morph_close,
        min_length=req.min_length,
        simplify_eps=req.simplify_eps,
        prune_branches=req.prune_branches,
        n_colors=req.n_colors,
        max_frames=req.max_frames,
        sam_cache_id=req.sam_cache_id,
    )
    existing = stroke_video.read_manifest(job.cache_id)
    if existing and existing.get("status") == "done":
        return {"cache_id": job.cache_id, "status": "done", "cached": True, "manifest": existing}

    stroke_video.write_manifest(job.cache_id, {
        "cache_id": job.cache_id,
        "status": "queued",
        "video_path": job.video_path,
        "method": job.method,
        "stride": job.stride,
        "progress": 0.0,
    })
    background.add_task(_run_stroke_video, job)
    return {"cache_id": job.cache_id, "status": "queued", "cached": False}


@stroke_router.get("/video-jobs/{cache_id}")
def video_job_status(cache_id: str):
    m = stroke_video.read_manifest(cache_id)
    if not m:
        raise HTTPException(status_code=404, detail="unknown cache_id")
    return m
