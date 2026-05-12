"""Convert stroke-art raster images into laser polylines via centerline extraction.

Three methods are exposed; each returns a list of `{points, color}` polylines using
the same shape the visualizer / ILDA exporter already consumes.

  - skeletonize_polylines     — single-pass: brightness-threshold → close → skeleton → trace
  - per_color_polylines       — same, but split by k-means color buckets first
  - potrace_polylines         — Potrace bezier fit on the brightness mask, sampled to points

Designed for AI-generated "neon stroke" art on a dark background. The stroke
itself is the foreground; we extract the medial axis (centerline), not the
stroke's outer boundary.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ---------- shared helpers ----------

def _read_image_bgr(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        # PIL fallback (avif/heic/etc.)
        try:
            from PIL import Image  # type: ignore
            with Image.open(path) as pim:
                arr = np.array(pim.convert("RGB"))
            img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise FileNotFoundError(f"could not read image {path}: {e}")
    return img


def _sam_mask_for(sam_cache_id: str, frame_idx: int = 0) -> Optional[np.ndarray]:
    """Load a SAM cache mask PNG. Returns 0/255 grayscale or None if missing."""
    if not sam_cache_id:
        return None
    base = Path(__file__).resolve().parent.parent / "sam3_cache" / sam_cache_id / "mask"
    p = base / f"{frame_idx:06d}.png"
    if not p.exists():
        return None
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)


def _apply_sam_mask(img_bgr: np.ndarray, sam_cache_id: Optional[str], frame_idx: int = 0) -> np.ndarray:
    """Zero out pixels where the SAM mask is dark. Resizes the mask if needed."""
    if not sam_cache_id:
        return img_bgr
    mask = _sam_mask_for(sam_cache_id, frame_idx)
    if mask is None:
        return img_bgr
    if mask.shape[:2] != img_bgr.shape[:2]:
        mask = cv2.resize(mask, (img_bgr.shape[1], img_bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    out = img_bgr.copy()
    out[mask == 0] = 0
    return out


def _brightness_mask(img_bgr: np.ndarray, threshold: int, morph_close: int) -> np.ndarray:
    """White wherever the image's HSV value exceeds threshold. Pre-closes to seal small gaps."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    _, mask = cv2.threshold(hsv[..., 2], threshold, 255, cv2.THRESH_BINARY)
    if morph_close > 0:
        kernel = np.ones((morph_close, morph_close), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _skeletonize(binary_mask: np.ndarray) -> np.ndarray:
    """Reduce a thick mask to a 1-pixel-wide centerline (boolean array)."""
    from skimage.morphology import skeletonize
    return skeletonize(binary_mask > 0)


def _prune_skeleton(skeleton: np.ndarray, iterations: int) -> np.ndarray:
    """Iteratively shave skeleton endpoints. Removes branches up to `iterations` long.

    Skeletons of filled regions have lots of short noisy side-branches at every
    boundary concavity. Removing degree-1 pixels for N iterations kills any
    branch shorter than N pixels while preserving the main spine.
    """
    if iterations <= 0:
        return skeleton
    sk = skeleton.astype(np.uint8)
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    for _ in range(int(iterations)):
        nb = cv2.filter2D(sk, -1, kernel) * sk
        endpoints = (nb == 1) & (sk == 1)
        if not endpoints.any():
            break
        sk[endpoints] = 0
    return sk.astype(bool)


def _color_at(img_bgr: np.ndarray, x: float, y: float) -> Tuple[int, int, int]:
    h, w = img_bgr.shape[:2]
    xi = max(0, min(w - 1, int(round(x))))
    yi = max(0, min(h - 1, int(round(y))))
    b, g, r = img_bgr[yi, xi]
    return (int(r), int(g), int(b))


# ---------- skeleton tracer ----------

# 8-connected neighbor offsets, prioritized so straight runs come first.
_NEIGHBORS = [(-1, 0), (1, 0), (0, -1), (0, 1),
              (-1, -1), (-1, 1), (1, -1), (1, 1)]


def _trace_skeleton(skeleton: np.ndarray, color_provider: Callable[[float, float], Tuple[int, int, int]],
                    min_length: int = 8) -> List[Dict]:
    """Walk a boolean skeleton into ordered polylines, breaking at junctions.

    Each polyline corresponds to one "edge" in the skeleton graph — i.e. a path
    between two endpoints (degree 1) or junctions (degree >= 3), with no
    branching mid-line. Closed loops are emitted as a single polyline.
    """
    h, w = skeleton.shape
    sk = skeleton.astype(np.uint8)
    if sk.sum() == 0:
        return []

    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    nb_count = cv2.filter2D(sk, -1, kernel) * sk
    is_junction = (nb_count >= 3) & (sk == 1)

    # We mark interior pixels (degree 2 or endpoints) as "visited" once consumed.
    # Junctions are NEVER consumed — they're shared connectors that may be the
    # endpoint of multiple segments.
    visited = np.zeros_like(sk, dtype=bool)
    polylines: List[Dict] = []

    def emit(path):
        if len(path) < min_length:
            return
        pts = [[int(x), int(y)] for y, x in path]
        mid = pts[len(pts) // 2]
        color = color_provider(mid[0], mid[1])
        polylines.append({"points": pts, "color": list(color)})

    def walk_segment(start_y: int, start_x: int):
        """Walk from a junction or endpoint into an unvisited neighbor and follow
        until we hit another endpoint, junction, or dead-end. Junctions cap the
        path but are themselves not consumed."""
        # Pick the first unvisited non-junction neighbor of start.
        for dy, dx in _NEIGHBORS:
            ny, nx = start_y + dy, start_x + dx
            if ny < 0 or ny >= h or nx < 0 or nx >= w: continue
            if not skeleton[ny, nx] or visited[ny, nx] or is_junction[ny, nx]: continue
            # Walk
            path = [(start_y, start_x), (ny, nx)]
            visited[ny, nx] = True
            py, px = ny, nx
            while True:
                nxt = None
                hit_junction = None
                for ddy, ddx in _NEIGHBORS:
                    yy, xx = py + ddy, px + ddx
                    if yy < 0 or yy >= h or xx < 0 or xx >= w: continue
                    if not skeleton[yy, xx]: continue
                    if visited[yy, xx]: continue
                    if is_junction[yy, xx]:
                        hit_junction = (yy, xx)
                        continue
                    nxt = (yy, xx)
                    break
                if nxt is None:
                    if hit_junction is not None:
                        path.append(hit_junction)
                    return path
                visited[nxt] = True
                path.append(nxt)
                py, px = nxt
        return None

    # 1) Walk every segment leaving each endpoint (degree 1).
    ys, xs = np.where(skeleton & (nb_count == 1))
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if visited[sy, sx]: continue
        visited[sy, sx] = True
        seg = walk_segment(sy, sx)
        if seg: emit(seg)

    # 2) Walk every segment leaving each junction. A junction can have many edges;
    #    we keep emitting segments from it until no unvisited neighbor remains.
    ys, xs = np.where(is_junction)
    for jy, jx in zip(ys.tolist(), xs.tolist()):
        while True:
            seg = walk_segment(jy, jx)
            if not seg: break
            emit(seg)

    # 3) Anything left is a closed loop (no endpoints, no junctions involved).
    ys, xs = np.where(skeleton & ~visited & ~is_junction)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if visited[sy, sx]: continue
        # Walk a free chain
        path = [(sy, sx)]; visited[sy, sx] = True
        py, px = sy, sx
        while True:
            nxt = None
            for dy, dx in _NEIGHBORS:
                ny, nx = py + dy, px + dx
                if ny < 0 or ny >= h or nx < 0 or nx >= w: continue
                if not skeleton[ny, nx] or visited[ny, nx] or is_junction[ny, nx]: continue
                nxt = (ny, nx); break
            if nxt is None: break
            visited[nxt] = True; path.append(nxt); py, px = nxt
        emit(path)

    return polylines


def _simplify_polylines(polylines: List[Dict], eps: float, closed: bool = False) -> List[Dict]:
    """Douglas-Peucker simplify each polyline. eps in pixels."""
    if eps <= 0:
        return polylines
    out = []
    for pl in polylines:
        if len(pl["points"]) < 3:
            out.append(pl)
            continue
        pts = np.array(pl["points"], dtype=np.float32).reshape(-1, 1, 2)
        approx = cv2.approxPolyDP(pts, eps, closed)
        out.append({"points": approx.reshape(-1, 2).astype(int).tolist(), "color": pl["color"]})
    return out


# ---------- METHOD D: neon-on-black ridge centerline ----------

def neon_centerline_polylines(
    image_path: str,
    *,
    sigmas: Tuple[float, ...] = (1.0, 2.0, 4.0),
    ridge_threshold: float = 0.04,
    min_length: int = 12,
    simplify_eps: float = 1.5,
    prune_branches: int = 4,
    morph_close: int = 0,
    sam_cache_id: Optional[str] = None,
    sam_frame_idx: int = 0,
) -> List[Dict]:
    """Single-line-per-stroke detector tuned for neon-on-black inputs.

    Instead of edge detection (which gives two parallel lines around each
    glowing stroke), this uses a ridge filter that directly responds to
    line-like structures, producing a single ~1-pixel response down the
    centerline regardless of stroke thickness. Color is sampled from the
    underlying image at each polyline midpoint, so the rendered output
    matches the input's neon palette.

    sigmas controls the range of stroke thicknesses you want to detect
    (each value is roughly one stroke-radius in pixels at native resolution).
    """
    try:
        from skimage.filters import meijering
    except ImportError as e:
        raise RuntimeError("scikit-image not installed: pip install scikit-image") from e

    img = _read_image_bgr(image_path)
    img = _apply_sam_mask(img, sam_cache_id, sam_frame_idx)
    # Use HSV value channel — equally responsive to bright cyan, magenta,
    # yellow, etc., without bias toward any single hue.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2].astype(np.float32) / 255.0

    response = meijering(v, sigmas=list(sigmas), black_ridges=False)

    mask = response > float(ridge_threshold)
    if morph_close > 0:
        kernel = np.ones((morph_close, morph_close), np.uint8)
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel) > 0

    sk = _skeletonize(mask)
    sk = _prune_skeleton(sk, prune_branches)

    polylines = _trace_skeleton(sk, lambda x, y: _color_at(img, x, y), min_length=min_length)
    return _simplify_polylines(polylines, simplify_eps)


# ---------- METHOD A: brightness-threshold skeleton ----------

def skeletonize_polylines(
    image_path: str,
    *,
    brightness_threshold: int = 90,
    morph_close: int = 3,
    min_length: int = 12,
    simplify_eps: float = 1.5,
    prune_branches: int = 8,
    sam_cache_id: Optional[str] = None,
    sam_frame_idx: int = 0,
) -> List[Dict]:
    img = _read_image_bgr(image_path)
    img = _apply_sam_mask(img, sam_cache_id, sam_frame_idx)
    mask = _brightness_mask(img, brightness_threshold, morph_close)
    sk = _skeletonize(mask)
    sk = _prune_skeleton(sk, prune_branches)
    polylines = _trace_skeleton(sk, lambda x, y: _color_at(img, x, y), min_length=min_length)
    return _simplify_polylines(polylines, simplify_eps)


# ---------- METHOD B: per-color k-means skeleton ----------

def per_color_polylines(
    image_path: str,
    *,
    n_colors: int = 5,
    brightness_threshold: int = 30,
    morph_close: int = 3,
    min_length: int = 15,
    simplify_eps: float = 1.5,
    min_cluster_pixels: int = 200,
    prune_branches: int = 6,
    sam_cache_id: Optional[str] = None,
    sam_frame_idx: int = 0,
) -> List[Dict]:
    from sklearn.cluster import MiniBatchKMeans

    img = _read_image_bgr(image_path)
    img = _apply_sam_mask(img, sam_cache_id, sam_frame_idx)
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] > brightness_threshold
    if bright.sum() < n_colors * 4:
        return []

    bright_pixels_bgr = img[bright]
    # Cluster in LAB for perceptual color similarity (separates yellow/orange better than RGB).
    lab = cv2.cvtColor(bright_pixels_bgr.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)

    km = MiniBatchKMeans(n_clusters=int(n_colors), n_init=4, random_state=42,
                         max_iter=80, batch_size=4096)
    labels = km.fit_predict(lab)

    label_image = np.full((h, w), -1, dtype=np.int32)
    label_image[bright] = labels

    polylines: List[Dict] = []
    for k in range(int(n_colors)):
        mask_k = (label_image == k).astype(np.uint8) * 255
        if int(mask_k.sum()) < min_cluster_pixels * 255:
            continue
        if morph_close > 0:
            kernel = np.ones((morph_close, morph_close), np.uint8)
            mask_k = cv2.morphologyEx(mask_k, cv2.MORPH_CLOSE, kernel)
        sk = _skeletonize(mask_k)
        sk = _prune_skeleton(sk, prune_branches)
        # Cluster mean color in BGR → RGB tuple.
        bgr_mean = img[label_image == k].mean(axis=0).astype(int)
        color = (int(bgr_mean[2]), int(bgr_mean[1]), int(bgr_mean[0]))
        cluster_polylines = _trace_skeleton(sk, lambda x, y, c=color: c, min_length=min_length)
        polylines.extend(cluster_polylines)

    return _simplify_polylines(polylines, simplify_eps)


# ---------- METHOD C: Potrace bezier outline ----------

def _potrace_mask_to_polylines(mask: np.ndarray, color: Tuple[int, int, int],
                                samples_per_segment: int, turdsize: int,
                                alphamax: float) -> List[Dict]:
    """Run Potrace on a single binary mask, return polylines with the given color."""
    import potrace
    bitmap = potrace.Bitmap(mask > 0)
    path = bitmap.trace(turdsize=int(turdsize), alphamax=float(alphamax))

    def _xy(p):
        if hasattr(p, "x") and hasattr(p, "y"):
            return float(p.x), float(p.y)
        return float(p[0]), float(p[1])

    def bezier_xy(p0, p1, p2, p3, t):
        u = 1.0 - t
        x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
        y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
        return float(x), float(y)

    polylines: List[Dict] = []
    for curve in path:
        prev = _xy(curve.start_point)
        pts: List[List[float]] = [[prev[0], prev[1]]]
        for seg in curve.segments:
            end = _xy(seg.end_point)
            if seg.is_corner:
                c = _xy(seg.c)
                pts.append([c[0], c[1]])
                pts.append([end[0], end[1]])
            else:
                c1 = _xy(seg.c1); c2 = _xy(seg.c2)
                for i in range(1, samples_per_segment + 1):
                    t = i / samples_per_segment
                    bx, by = bezier_xy(prev, c1, c2, end, t)
                    pts.append([bx, by])
            prev = end
        if len(pts) < 4:
            continue
        polylines.append({
            "points": [[int(round(x)), int(round(y))] for x, y in pts],
            "color": list(color),
        })
    return polylines


def potrace_polylines(
    image_path: str,
    *,
    n_colors: int = 5,
    brightness_threshold: int = 30,
    morph_close: int = 3,
    simplify_eps: float = 1.5,
    samples_per_segment: int = 8,
    turdsize: int = 8,
    alphamax: float = 1.0,
    min_cluster_pixels: int = 300,
    sam_cache_id: Optional[str] = None,
    sam_frame_idx: int = 0,
) -> List[Dict]:
    """Per-color smooth Bezier vector traces via Potrace.

    For each k-means color bucket, run Potrace and emit the smooth outline
    curves. Unlike a single-blob potrace (which loses interior detail on filled
    drawings), this preserves every colored region as its own smooth curves.
    """
    try:
        import potrace  # noqa: F401  pure-python `potracer` installs as `potrace`
    except ImportError as e:
        raise RuntimeError("potrace package not installed: pip install potracer") from e

    from sklearn.cluster import MiniBatchKMeans

    img = _read_image_bgr(image_path)
    img = _apply_sam_mask(img, sam_cache_id, sam_frame_idx)
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] > brightness_threshold
    if bright.sum() < n_colors * 4:
        return []

    bright_pixels_bgr = img[bright]
    lab = cv2.cvtColor(bright_pixels_bgr.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    km = MiniBatchKMeans(n_clusters=int(n_colors), n_init=4, random_state=42,
                         max_iter=80, batch_size=4096)
    labels = km.fit_predict(lab)

    label_image = np.full((h, w), -1, dtype=np.int32)
    label_image[bright] = labels

    polylines: List[Dict] = []
    for k in range(int(n_colors)):
        mask_k = (label_image == k).astype(np.uint8) * 255
        if int((mask_k > 0).sum()) < min_cluster_pixels:
            continue
        if morph_close > 0:
            kernel = np.ones((morph_close, morph_close), np.uint8)
            mask_k = cv2.morphologyEx(mask_k, cv2.MORPH_CLOSE, kernel)
        bgr_mean = img[label_image == k].mean(axis=0).astype(int)
        color = (int(bgr_mean[2]), int(bgr_mean[1]), int(bgr_mean[0]))
        cluster = _potrace_mask_to_polylines(
            mask_k > 0, color, samples_per_segment, turdsize, alphamax,
        )
        polylines.extend(cluster)

    return _simplify_polylines(polylines, simplify_eps, closed=True)
