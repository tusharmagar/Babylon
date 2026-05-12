"""HTTP routes for SAM 3 processing + ILDA export from polylines.

Mounted onto the main FastAPI app via include_router(sam3_router).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from services import sam3_processor
from services.ilda_writer import write_ilda_file
from models.laser_types import LaserFrame, LaserPoint

logger = logging.getLogger(__name__)

sam3_router = APIRouter(prefix="/api/sam3", tags=["sam3"])
laser_export_router = APIRouter(prefix="/api/laser", tags=["laser-export"])

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / "ilda_exports"
EXPORT_DIR.mkdir(exist_ok=True)
FIRSTFRAME_DIR = ROOT / "sam3_cache" / "_firstframes"
FIRSTFRAME_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = ROOT / "sam3_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Track in-flight jobs so duplicate POSTs don't double-run.
_jobs_lock = threading.Lock()
_running: set[str] = set()


# ---------- request models ----------

class ProcessRequest(BaseModel):
    video_path: str
    prompt_type: str = Field(pattern="^(text|bbox)$")
    prompt_value: str
    parts: List[str] = Field(default_factory=list)
    imgsz: int = 640
    process_every_n: int = 1
    max_frames: Optional[int] = None
    media_type: Optional[str] = None  # "image" | "video"; if omitted backend autodetects by extension


class FirstFrameRequest(BaseModel):
    video_path: str


class Polyline(BaseModel):
    points: List[List[float]]            # pixel coords [[x,y], ...]
    color: List[int] = Field(default_factory=lambda: [255, 255, 255])  # rgb 0..255


class IldaExportRequest(BaseModel):
    width: int
    height: int
    polylines: List[Polyline] = Field(default_factory=list)
    filename: Optional[str] = None
    invert_y: bool = True


class IldaFrame(BaseModel):
    width: int
    height: int
    polylines: List[Polyline] = Field(default_factory=list)
    timestamp_ms: float = 0.0


class IldaMultiExportRequest(BaseModel):
    frames: List[IldaFrame] = Field(default_factory=list)
    filename: Optional[str] = None
    invert_y: bool = True


# ---------- helpers ----------

def _resolve_local_path(p: str) -> Path:
    rp = Path(p).expanduser().resolve()
    if not rp.exists() or not rp.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {rp}")
    return rp


def _polyline_to_laser_points(
    pl: Polyline, width: int, height: int, *, invert_y: bool
) -> List[LaserPoint]:
    """Pixel-space polyline → ILDA int16 LaserPoints with leading blanked travel."""
    pts = pl.points
    if not pts:
        return []
    r, g, b = (int(c) & 0xFF for c in (pl.color + [255, 255, 255])[:3])

    out: List[LaserPoint] = []
    for idx, (x, y) in enumerate(pts):
        nx = (float(x) / max(width - 1, 1)) * 2.0 - 1.0
        ny_raw = (float(y) / max(height - 1, 1)) * 2.0 - 1.0
        ny = -ny_raw if invert_y else ny_raw
        ix = max(-32768, min(32767, int(round(nx * 32767))))
        iy = max(-32768, min(32767, int(round(ny * 32767))))
        # First point is a blanked travel so the galvo gets there before drawing.
        blanked = idx == 0
        out.append(LaserPoint(x=ix, y=iy, r=r, g=g, b=b, blanked=blanked))
    return out


def _build_single_frame(req: IldaExportRequest) -> LaserFrame:
    points: List[LaserPoint] = []
    for pl in req.polylines:
        points.extend(_polyline_to_laser_points(pl, req.width, req.height, invert_y=req.invert_y))
    return LaserFrame(points=points, timestamp_ms=0.0)


# ---------- SAM endpoints ----------

@sam3_router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Stream a browser-picked video to disk so SAM has a real path to work with."""
    import hashlib
    import shutil

    suffix = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    h = hashlib.sha1()
    tmp = UPLOAD_DIR / f"_tmp_{os.getpid()}_{int(__import__('time').time()*1000)}{suffix}"
    with tmp.open("wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            out.write(chunk)
    final_name = f"{h.hexdigest()[:12]}{suffix}"
    final = UPLOAD_DIR / final_name
    if final.exists():
        tmp.unlink(missing_ok=True)
    else:
        shutil.move(str(tmp), str(final))
    return {
        "path": str(final),
        "url": f"/api/sam3/local-file?path={final}",
        "filename": file.filename,
        "size": final.stat().st_size,
        "media_type": sam3_processor.detect_media_type(str(final)),
    }


@sam3_router.post("/first-frame")
def first_frame(req: FirstFrameRequest):
    src = _resolve_local_path(req.video_path)
    media_type = sam3_processor.detect_media_type(str(src))
    if media_type == "image":
        import cv2
        out = FIRSTFRAME_DIR / (src.stem + ".png")
        img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if img is None:
            # PIL fallback for avif/heic and other formats cv2 can't decode.
            try:
                from PIL import Image
                with Image.open(str(src)) as pim:
                    pim.convert("RGBA").save(str(out), format="PNG")
                    w, h = pim.size
                return {"width": int(w), "height": int(h),
                        "url": f"/sam3_cache/_firstframes/{out.name}"}
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"could not read image: {src}: {e}")
        h, w = img.shape[:2]
        if not out.exists():
            cv2.imwrite(str(out), img)
        return {"width": int(w), "height": int(h), "url": f"/sam3_cache/_firstframes/{out.name}"}

    out = FIRSTFRAME_DIR / (src.stem + ".png")
    w, h = sam3_processor.grab_first_frame_png(str(src), out)
    return {"width": w, "height": h, "url": f"/sam3_cache/_firstframes/{out.name}"}


@sam3_router.get("/local-file")
def local_file(path: str = Query(...)):
    """Serve any local file by absolute path. Local-only convenience."""
    src = _resolve_local_path(path)
    suffix = src.suffix.lower()
    media_map = {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".m4v": "video/mp4",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".bmp": "image/bmp", ".tiff": "image/tiff", ".tif": "image/tiff",
    }
    return FileResponse(str(src), media_type=media_map.get(suffix, "application/octet-stream"))


def _run_in_background(job: sam3_processor.Sam3Job, max_frames: Optional[int]):
    cid = job.cache_id
    try:
        with _jobs_lock:
            if cid in _running:
                return
            _running.add(cid)
        sam3_processor.run_job(job, max_frames=max_frames)
    finally:
        with _jobs_lock:
            _running.discard(cid)


@sam3_router.post("/process")
def process_video(req: ProcessRequest, background: BackgroundTasks):
    src = _resolve_local_path(req.video_path)
    job = sam3_processor.plan_job(
        video_path=str(src),
        prompt_type=req.prompt_type,
        prompt_value=req.prompt_value,
        parts=req.parts,
        imgsz=req.imgsz,
        process_every_n=req.process_every_n,
        media_type=req.media_type,
    )

    existing = sam3_processor.read_manifest(job.cache_id)
    if existing and existing.get("status") == "done":
        return {"cache_id": job.cache_id, "status": "done", "cached": True, "manifest": existing}

    # Initial manifest so the poller has something to read instantly.
    sam3_processor.write_manifest(job.cache_id, {
        "cache_id": job.cache_id,
        "status": "queued",
        "video_path": job.video_path,
        "prompt_type": job.prompt_type,
        "prompt_value": job.prompt_value,
        "parts": job.parts,
        "progress": 0.0,
    })
    background.add_task(_run_in_background, job, req.max_frames)
    return {"cache_id": job.cache_id, "status": "queued", "cached": False}


@sam3_router.get("/jobs/{cache_id}")
def job_status(cache_id: str):
    m = sam3_processor.read_manifest(cache_id)
    if not m:
        raise HTTPException(status_code=404, detail="unknown cache_id")
    return m


@sam3_router.post("/jobs/{cache_id}/cancel")
def cancel_job(cache_id: str):
    """Best-effort: cancel the in-flight Fal request and mark the manifest cancelled."""
    m = sam3_processor.read_manifest(cache_id)
    if not m:
        raise HTTPException(status_code=404, detail="unknown cache_id")
    if m.get("status") in ("done", "error", "cancelled"):
        return {"already": m.get("status")}

    rid = m.get("fal_request_id")
    cancelled = False
    if rid:
        try:
            import fal_client
            # try both endpoints — we don't track which one is active
            for app in ("fal-ai/sam-3-1/image", "fal-ai/sam-3-1/video"):
                try: fal_client.cancel(app, rid); cancelled = True; break
                except Exception: pass
        except Exception as e:
            logger.warning("fal_client.cancel failed: %s", e)

    m["status"] = "cancelled"
    m["error"] = "cancelled by user"
    sam3_processor.write_manifest(cache_id, m)
    return {"cancelled": cancelled, "request_id": rid}


# ---------- laser export ----------

@laser_export_router.post("/ild-export")
def ild_export(req: IldaExportRequest):
    if not req.polylines:
        raise HTTPException(status_code=400, detail="no polylines provided")
    frame = _build_single_frame(req)
    if not frame.points:
        raise HTTPException(status_code=400, detail="no laser points generated from polylines")

    name = req.filename or f"frame_{int(__import__('time').time())}.ild"
    if not name.lower().endswith(".ild"):
        name += ".ild"
    out = EXPORT_DIR / name
    write_ilda_file([frame], out)
    return FileResponse(
        str(out),
        media_type="application/octet-stream",
        filename=out.name,
    )


@laser_export_router.post("/ild-multi-export")
def ild_multi_export(req: IldaMultiExportRequest):
    """Pack many polyline-frames into a single multi-frame ILDA file."""
    if not req.frames:
        raise HTTPException(status_code=400, detail="no frames provided")

    out_frames: List[LaserFrame] = []
    for f in req.frames:
        pts: List[LaserPoint] = []
        for pl in f.polylines:
            pts.extend(_polyline_to_laser_points(pl, f.width, f.height, invert_y=req.invert_y))
        out_frames.append(LaserFrame(points=pts, timestamp_ms=float(f.timestamp_ms)))

    if not any(fr.points for fr in out_frames):
        raise HTTPException(status_code=400, detail="no laser points generated from any frame")

    name = req.filename or f"show_{int(__import__('time').time())}.ild"
    if not name.lower().endswith(".ild"):
        name += ".ild"
    out = EXPORT_DIR / name
    write_ilda_file(out_frames, out)
    return FileResponse(
        str(out),
        media_type="application/octet-stream",
        filename=out.name,
    )
