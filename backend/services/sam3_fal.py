"""SAM 3 via Fal.ai (`fal-ai/sam-3-1/video`).

Drop-in replacement for the local Ultralytics path. Same cache layout so the
visualizer doesn't change:

    backend/sam3_cache/<cache_id>/
        manifest.json
        mask/000000.png ... 000NNN.png
        parts/<part_slug>/000000.png ... 000NNN.png
        _fal/                  # raw Fal artifacts (downloaded videos, etc.)

Strategy: submit one job per concept (main + each part). Each Fal job returns a
masked .mp4 (background black). We extract a binary mask per frame by
thresholding on luminance, save as PNG, then drop the .mp4.
"""
from __future__ import annotations

import logging
import os
import time
import traceback
import urllib.request
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _download(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as r, open(dst, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dst


def _extract_masks_from_video(video_path: Path, out_dir: Path, *, lum_threshold: int = 5) -> int:
    """Walk a Fal-segmented video and dump per-frame binary masks.

    The Fal output (apply_mask=true) keeps subject pixels and blacks out the
    background. So: mask[y,x] = 255 if luminance(frame[y,x]) > threshold else 0.
    Returns frame count.
    """
    import cv2
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open Fal output video: {video_path}")

    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, lum_threshold, 255, cv2.THRESH_BINARY)
        # close small holes inside the subject
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        cv2.imwrite(str(out_dir / f"{n:06d}.png"), mask)
        n += 1
    cap.release()
    return n


DEFAULT_IMAGE_TIMEOUT = 180.0   # seconds — image jobs should be quick
DEFAULT_VIDEO_TIMEOUT = 900.0   # seconds — videos can take a while
POLL_INTERVAL = 2.5             # seconds between status checks


def _fal_run_polled(
    app: str,
    arguments: dict,
    *,
    timeout: float,
    poll_interval: float = POLL_INTERVAL,
    on_progress=None,
    on_request_id=None,
) -> dict:
    """Submit a Fal job, poll status with a hard wall-clock timeout, return result.

    Raises TimeoutError if the job doesn't reach Completed within `timeout`. Replaces
    `fal_client.subscribe`, which polls ~3×/sec with no timeout (logs flood, no recovery).
    """
    import fal_client

    handle = fal_client.submit(app, arguments=arguments)
    request_id = getattr(handle, "request_id", None)
    if on_request_id and request_id:
        try: on_request_id(request_id)
        except Exception: pass

    deadline = time.time() + timeout
    last_state = None
    while True:
        if time.time() > deadline:
            try: fal_client.cancel(app, request_id)
            except Exception: pass
            raise TimeoutError(
                f"Fal {app} request {request_id} did not complete within {timeout:.0f}s"
            )

        try:
            st = fal_client.status(app, request_id, with_logs=False)
        except Exception as e:
            logger.warning("Fal status check failed (will retry): %s", e)
            time.sleep(poll_interval)
            continue

        st_name = type(st).__name__
        if st_name != last_state:
            logger.info("Fal %s [%s] state=%s", app, request_id, st_name)
            last_state = st_name
        if on_progress:
            try: on_progress(st_name, st)
            except Exception: pass

        if st_name == "Completed":
            return fal_client.result(app, request_id)

        time.sleep(poll_interval)


def _run_fal_segmentation(
    *,
    video_url: str,
    prompt: str,
    box_prompts: Optional[list],
    on_progress=None,
    on_request_id=None,
    timeout: float = DEFAULT_VIDEO_TIMEOUT,
) -> dict:
    """Submit a single Fal sam-3-1/video job."""
    inp: dict = {
        "video_url": video_url,
        "apply_mask": True,
        "video_output_type": "X264 (.mp4)",
    }
    if prompt: inp["prompt"] = prompt
    if box_prompts: inp["box_prompts"] = box_prompts
    return _fal_run_polled(
        "fal-ai/sam-3-1/video", inp,
        timeout=timeout, on_progress=on_progress, on_request_id=on_request_id,
    )


def _run_fal_image_segmentation(
    *,
    image_url: str,
    prompt: str,
    box_prompts: Optional[list],
    on_progress=None,
    on_request_id=None,
    timeout: float = DEFAULT_IMAGE_TIMEOUT,
) -> dict:
    """Submit a single Fal sam-3-1/image job."""
    inp: dict = {
        "image_url": image_url,
        "apply_mask": True,
        "output_format": "png",
    }
    if prompt: inp["prompt"] = prompt
    if box_prompts: inp["box_prompts"] = box_prompts
    return _fal_run_polled(
        "fal-ai/sam-3-1/image", inp,
        timeout=timeout, on_progress=on_progress, on_request_id=on_request_id,
    )


def _save_mask_from_masked_image(masked_image_path: Path, out_png: Path, *, lum_threshold: int = 5) -> None:
    """Convert a Fal-segmented image (subject visible, background black) into a binary mask PNG."""
    import cv2
    import numpy as np

    img = cv2.imread(str(masked_image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"could not read masked image: {masked_image_path}")
    if img.ndim == 3 and img.shape[2] == 4:
        # has alpha — use it directly
        mask = (img[:, :, 3] > 0).astype("uint8") * 255
    else:
        gray = cv2.cvtColor(img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, lum_threshold, 255, cv2.THRESH_BINARY)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), mask)


def _save_mask_from_mask_image(mask_image_path: Path, out_png: Path) -> None:
    """Save a Fal-returned *mask* image (already a true mask) as a clean 0/255 PNG.

    Handles 1-channel, 3-channel, and 4-channel inputs. Anything > 0 becomes 255.
    """
    import cv2
    import numpy as np

    img = cv2.imread(str(mask_image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"could not read mask image: {mask_image_path}")
    if img.ndim == 3 and img.shape[2] == 4:
        ref = img[:, :, 3]
    elif img.ndim == 3:
        ref = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        ref = img
    mask = (ref > 0).astype("uint8") * 255
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), mask)


def _extract_image_mask_from_result(result: dict, fal_dir: Path, mask_out: Path, slug_for_filename: str = "main") -> None:
    """Pull the cleanest mask out of a Fal sam-3-1/image response.

    Prefers `result.masks[0]` (a true mask). Falls back to thresholding `result.image`.
    """
    masks_list = (result or {}).get("masks") or []
    if masks_list and isinstance(masks_list[0], dict) and masks_list[0].get("url"):
        downloaded = fal_dir / f"{slug_for_filename}_mask.png"
        _download(masks_list[0]["url"], downloaded)
        _save_mask_from_mask_image(downloaded, mask_out)
        return
    img_obj = (result or {}).get("image") or {}
    if img_obj.get("url"):
        downloaded = fal_dir / f"{slug_for_filename}_preview.png"
        _download(img_obj["url"], downloaded)
        _save_mask_from_masked_image(downloaded, mask_out)
        return
    raise RuntimeError(f"unexpected Fal image response (no masks[] or image): {result}")


def _upload_local_video(path: str) -> str:
    """Upload a local file via Fal storage; return public URL."""
    import fal_client
    return fal_client.upload_file(path)


def run_job(job, write_manifest, *, max_frames: Optional[int] = None) -> dict:
    """Fal-backed implementation of the run_job contract used by sam3_processor.

    `job` is a Sam3Job dataclass. `write_manifest(cache_id, dict)` persists state.
    """
    from services import sam3_processor as core  # for cache_dir_for / manifest helpers
    import cv2

    cache = core.cache_dir_for(job.cache_id)
    cache.mkdir(parents=True, exist_ok=True)
    fal_dir = cache / "_fal"
    fal_dir.mkdir(exist_ok=True)
    mask_dir = cache / "mask"
    parts_root = cache / "parts"

    is_image = (job.media_type == "image")

    # gather media meta
    if is_image:
        # cv2 doesn't decode avif/heic without the right codec installed —
        # fall back to PIL which handles a much wider range natively.
        img = cv2.imread(job.video_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            try:
                from PIL import Image  # type: ignore
                with Image.open(job.video_path) as pim:
                    width, height = pim.size
            except Exception as e:
                raise RuntimeError(f"cannot open image (cv2 + PIL both failed): {job.video_path}: {e}")
        else:
            height, width = img.shape[:2]
        fps = 1.0
        n_frames = 1
    else:
        cap = cv2.VideoCapture(job.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {job.video_path}")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()

    manifest = {
        "cache_id": job.cache_id,
        "status": "running",
        "provider": "fal",
        "started_at": time.time(),
        "media_type": job.media_type,
        "video_path": job.video_path,
        "video_width": width,
        "video_height": height,
        "video_fps": fps,
        "video_frames": n_frames,
        "prompt_type": job.prompt_type,
        "prompt_value": job.prompt_value,
        "parts": job.parts,
        "frames_processed": 0,
        "progress": 0.0,
        "error": None,
        "stage": "uploading",
    }
    write_manifest(job.cache_id, manifest)

    try:
        # 1) upload media once, reuse URL across all (main + parts) calls
        manifest["stage"] = "uploading"
        write_manifest(job.cache_id, manifest)
        media_url = _upload_local_video(job.video_path)
        manifest["video_url"] = media_url

        def _stage(label: str, frac: float):
            manifest["stage"] = label
            manifest["progress"] = frac
            write_manifest(job.cache_id, manifest)

        # 2) main concept run
        _stage("main: submitted", 0.1)
        prompt_text = ""
        box_prompts = None
        if job.prompt_type == "text":
            prompt_text = (job.prompt_value or "").strip()
        elif job.prompt_type == "bbox":
            coords = [int(float(x)) for x in job.prompt_value.replace(" ", ",").split(",") if x.strip()]
            if len(coords) != 4:
                raise ValueError(f"bbox must be 'x1,y1,x2,y2', got {job.prompt_value!r}")
            x1, y1, x2, y2 = coords
            if is_image:
                box_prompts = [{
                    "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
                    "object_id": 0,
                }]
            else:
                box_prompts = [{
                    "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
                    "object_id": 0, "frame_index": 0,
                }]

        def main_progress(status, update):
            manifest["fal_status"] = status
            # Surface queue state in the visible stage so the UI shows
            # "main: queued (waiting for Fal)" → "main: in_progress" → "main: completed".
            if status in ("Queued", "InProgress", "Completed"):
                manifest["stage"] = f"main: {status.lower()}"
                if status == "Queued":
                    manifest["stage"] += " (waiting for Fal capacity)"
            write_manifest(job.cache_id, manifest)
        def main_request_id(rid):
            manifest["fal_request_id"] = rid
            write_manifest(job.cache_id, manifest)

        if is_image:
            result = _run_fal_image_segmentation(
                image_url=media_url,
                prompt=prompt_text,
                box_prompts=box_prompts,
                on_progress=main_progress,
                on_request_id=main_request_id,
            )
            _stage("main: downloading mask", 0.55)
            _extract_image_mask_from_result(result, fal_dir, mask_dir / "000000.png", "main")
            manifest["frames_processed"] = 1
            manifest["main_pass_done"] = True
            _stage("main: done", 0.6 if job.parts else 1.0)
        else:
            result = _run_fal_segmentation(
                video_url=media_url,
                prompt=prompt_text,
                box_prompts=box_prompts,
                on_progress=main_progress,
                on_request_id=main_request_id,
            )
            video_obj = result.get("video") if isinstance(result, dict) else None
            if not video_obj or "url" not in video_obj:
                raise RuntimeError(f"unexpected Fal response (no video.url): {result}")
            masked_path = fal_dir / "main.mp4"
            _stage("main: downloading", 0.4)
            _download(video_obj["url"], masked_path)
            _stage("main: extracting masks", 0.5)
            produced = _extract_masks_from_video(masked_path, mask_dir)
            manifest["frames_processed"] = produced
            manifest["main_pass_done"] = True
            _stage("main: done", 0.6 if job.parts else 1.0)

        # 3) optional parts — one Fal call per part
        if job.parts:
            n_parts = len(job.parts)
            for i, part in enumerate(job.parts):
                slug = core._slug(part)
                pdir = parts_root / slug
                pdir.mkdir(parents=True, exist_ok=True)

                _stage(f"part '{slug}': submitted", 0.6 + 0.4 * (i / n_parts))

                def _part_progress(status, update, _slug=slug):
                    manifest[f"fal_status_{_slug}"] = status
                    write_manifest(job.cache_id, manifest)

                if is_image:
                    p_result = _run_fal_image_segmentation(
                        image_url=media_url,
                        prompt=part,
                        box_prompts=None,
                        on_progress=_part_progress,
                    )
                    try:
                        _extract_image_mask_from_result(p_result, fal_dir, pdir / "000000.png", f"part_{slug}")
                    except Exception as e:
                        logger.warning("Fal returned no usable mask for part '%s': %s", part, e)
                        continue
                else:
                    p_result = _run_fal_segmentation(
                        video_url=media_url,
                        prompt=part,
                        box_prompts=None,
                        on_progress=_part_progress,
                    )
                    p_video = (p_result or {}).get("video", {})
                    if not p_video.get("url"):
                        logger.warning("Fal returned no video for part '%s': %s", part, p_result)
                        continue
                    p_masked = fal_dir / f"part_{slug}.mp4"
                    _download(p_video["url"], p_masked)
                    _extract_masks_from_video(p_masked, pdir)
                manifest.setdefault("parts_done", []).append(slug)
                _stage(f"part '{slug}': done", 0.6 + 0.4 * ((i + 1) / n_parts))

        manifest["status"] = "done"
        manifest["progress"] = 1.0
        manifest["stage"] = "done"
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        return manifest

    except Exception as e:
        logger.exception("Fal SAM3 job failed")
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        manifest["traceback"] = traceback.format_exc()
        manifest["finished_at"] = time.time()
        write_manifest(job.cache_id, manifest)
        raise
