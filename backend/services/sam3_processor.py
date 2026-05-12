"""SAM 3 video segmentation/tracking, cached per (video, prompt) tuple.

Designed to feed the edge_visualizer pipeline: writes per-frame binary mask
PNGs that the browser fetches and uses to gate edge detection or to vectorize
directly into laser polylines.

Cache layout:
    backend/sam3_cache/<cache_id>/
        manifest.json
        mask/000000.png ... 000NNN.png
        parts/<part_name>/000000.png ...   (only if parts requested)

manifest.json includes status: queued|running|done|error so the frontend can poll.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(__file__).resolve().parent.parent / "sam3_cache"
CACHE_ROOT.mkdir(exist_ok=True)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
              ".avif", ".heic", ".heif", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}


def detect_media_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "video"  # default; the client should pass an explicit override for unknown


@dataclass
class Sam3Job:
    cache_id: str
    video_path: str           # historical name; holds image path too
    prompt_type: str          # "text" | "bbox"
    prompt_value: str         # text concept, or "x1,y1,x2,y2"
    parts: List[str]
    imgsz: int
    process_every_n: int
    media_type: str = "video" # "video" | "image"


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "x"


def _cache_key(video_path: str, prompt_type: str, prompt_value: str, parts: List[str], imgsz: int) -> str:
    p = Path(video_path).expanduser().resolve()
    try:
        mtime = int(p.stat().st_mtime)
    except FileNotFoundError:
        mtime = 0
    payload = "|".join([str(p), str(mtime), prompt_type, prompt_value, ",".join(parts), str(imgsz)])
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
    video_path: str,
    prompt_type: str,
    prompt_value: str,
    parts: Optional[List[str]] = None,
    imgsz: int = 640,
    process_every_n: int = 1,
    media_type: Optional[str] = None,
) -> Sam3Job:
    parts = [p.strip() for p in (parts or []) if p.strip()]
    if media_type not in ("image", "video"):
        media_type = detect_media_type(video_path)
    cache_id = _cache_key(video_path, prompt_type, prompt_value + "|" + media_type, parts, imgsz)
    return Sam3Job(
        cache_id=cache_id,
        video_path=str(Path(video_path).expanduser().resolve()),
        prompt_type=prompt_type,
        prompt_value=prompt_value,
        parts=parts,
        imgsz=imgsz,
        process_every_n=process_every_n,
        media_type=media_type,
    )


def _detect_device() -> Tuple[str, bool]:
    """Return (device, half) tuned for the host."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda", True
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps", False  # half on MPS often glitches with SAM
    except Exception:
        pass
    return "cpu", False


def _video_meta(video_path: str) -> Tuple[int, int, float, int]:
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return w, h, fps, n


def grab_first_frame_png(video_path: str, out_path: Path) -> Tuple[int, int]:
    """Write the first frame as PNG. Returns (width, height)."""
    import cv2

    p = str(Path(video_path).expanduser().resolve())
    cap = cv2.VideoCapture(p)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Could not read first frame: {p}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), frame)
    h, w = frame.shape[:2]
    return w, h


def _result_to_mask(result, h: int, w: int):
    """Combine all instance masks from an Ultralytics Results into one uint8 (0/255) image."""
    import cv2
    import numpy as np

    if result.masks is None:
        return np.zeros((h, w), dtype=np.uint8)
    data = result.masks.data
    if hasattr(data, "detach"):
        data = data.detach().float().cpu().numpy()
    if data.ndim == 2:
        data = data[None, ...]
    combined = np.zeros(data.shape[1:], dtype=np.uint8)
    for m in data:
        combined = np.maximum(combined, (m > 0.5).astype(np.uint8))
    if combined.shape[:2] != (h, w):
        combined = cv2.resize(combined, (w, h), interpolation=cv2.INTER_NEAREST)
    return (combined * 255).astype("uint8")


def _build_predictor(prompt_type: str, model_path: str, device: str, half: bool, imgsz: int):
    from ultralytics.models.sam import SAM3VideoPredictor, SAM3VideoSemanticPredictor

    overrides = dict(
        conf=0.25,
        task="segment",
        mode="predict",
        imgsz=imgsz,
        model=model_path,
        device=device,
        half=half,
        verbose=False,
    )
    if prompt_type == "bbox":
        return SAM3VideoPredictor(overrides=overrides)
    return SAM3VideoSemanticPredictor(overrides=overrides)


def _run_predictor(predictor, video_path: str, prompt_type: str, prompt_value: str):
    if prompt_type == "bbox":
        coords = [float(x) for x in re.split(r"[ ,]+", prompt_value.strip()) if x]
        if len(coords) != 4:
            raise ValueError(f"bbox prompt must be 'x1,y1,x2,y2', got: {prompt_value!r}")
        return predictor(source=video_path, bboxes=[coords], stream=True)
    text = (prompt_value or "").strip()
    if not text:
        raise ValueError("text prompt cannot be empty")
    return predictor(source=video_path, text=[text], stream=True)


def _resolve_model_path() -> str:
    """Find sam3.pt. Honors SAM3_MODEL_PATH env var, then common locations."""
    candidates = [
        os.environ.get("SAM3_MODEL_PATH"),
        str(Path.home() / "Downloads" / "sam3.pt"),
        str(Path(__file__).resolve().parent.parent / "models" / "sam3.pt"),
        str(Path(__file__).resolve().parent.parent / "sam3.pt"),
        "sam3.pt",
    ]
    for c in candidates:
        if c and Path(c).expanduser().exists():
            return str(Path(c).expanduser().resolve())
    raise FileNotFoundError(
        "sam3.pt not found. Set SAM3_MODEL_PATH or place sam3.pt in ~/Downloads/, "
        "backend/, or backend/models/."
    )


def run_job(job: Sam3Job, *, max_frames: Optional[int] = None) -> dict:
    """Execute the SAM 3 job. Updates manifest.json as it progresses.

    Provider is selected by SAM3_PROVIDER env var: "fal" (default) or "local".
    Returns the final manifest dict.
    """
    provider = (os.environ.get("SAM3_PROVIDER") or "fal").strip().lower()
    if provider == "fal":
        from services import sam3_fal
        return sam3_fal.run_job(job, write_manifest, max_frames=max_frames)
    return _run_job_local(job, max_frames=max_frames)


def _run_job_local(job: Sam3Job, *, max_frames: Optional[int] = None) -> dict:
    """Local Ultralytics implementation (kept as fallback)."""
    import cv2

    cache = cache_dir_for(job.cache_id)
    cache.mkdir(parents=True, exist_ok=True)
    mask_dir = cache / "mask"
    mask_dir.mkdir(exist_ok=True)
    parts_root = cache / "parts"

    w, h, fps, n_frames = _video_meta(job.video_path)
    device, half = _detect_device()
    model_path = _resolve_model_path()

    manifest = {
        "cache_id": job.cache_id,
        "status": "running",
        "started_at": time.time(),
        "video_path": job.video_path,
        "video_width": w,
        "video_height": h,
        "video_fps": fps,
        "video_frames": n_frames,
        "prompt_type": job.prompt_type,
        "prompt_value": job.prompt_value,
        "parts": job.parts,
        "imgsz": job.imgsz,
        "process_every_n": job.process_every_n,
        "device": device,
        "half": half,
        "model_path": model_path,
        "frames_processed": 0,
        "progress": 0.0,
        "error": None,
    }
    write_manifest(job.cache_id, manifest)

    try:
        # ---- main mask pass ----
        predictor = _build_predictor(job.prompt_type, model_path, device, half, job.imgsz)
        results = _run_predictor(predictor, job.video_path, job.prompt_type, job.prompt_value)

        processed = 0
        last_save = time.time()
        for i, r in enumerate(results):
            if max_frames is not None and i >= max_frames:
                break
            if i % job.process_every_n != 0:
                continue
            orig = r.orig_img
            fh, fw = orig.shape[:2]
            mask = _result_to_mask(r, fh, fw)
            cv2.imwrite(str(mask_dir / f"{i:06d}.png"), mask)
            processed += 1

            now = time.time()
            if now - last_save > 0.75:
                manifest["frames_processed"] = i + 1
                manifest["progress"] = (i + 1) / max(n_frames, 1)
                write_manifest(job.cache_id, manifest)
                last_save = now

        manifest["frames_processed"] = processed
        manifest["main_pass_done"] = True
        write_manifest(job.cache_id, manifest)

        # ---- optional parts passes (one per concept) ----
        # SAM 3 semantic predictor handles the concept; we run it once per part
        # so each gets its own clean per-frame mask file.
        if job.parts:
            for part in job.parts:
                part_slug = _slug(part)
                part_dir = parts_root / part_slug
                part_dir.mkdir(parents=True, exist_ok=True)
                p_pred = _build_predictor("text", model_path, device, half, job.imgsz)
                p_results = p_pred(source=job.video_path, text=[part], stream=True)
                for i, r in enumerate(p_results):
                    if max_frames is not None and i >= max_frames:
                        break
                    if i % job.process_every_n != 0:
                        continue
                    fh, fw = r.orig_img.shape[:2]
                    m = _result_to_mask(r, fh, fw)
                    cv2.imwrite(str(part_dir / f"{i:06d}.png"), m)
                manifest.setdefault("parts_done", []).append(part_slug)
                write_manifest(job.cache_id, manifest)

        manifest["status"] = "done"
        manifest["progress"] = 1.0
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        return manifest

    except Exception as e:
        logger.exception("SAM3 job failed")
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        manifest["traceback"] = traceback.format_exc()
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        raise
