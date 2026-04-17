"""Deterministic laser drawing primitives.

These produce point lists the LLM could never generate accurately. The LLM
picks which primitives to compose; this module does all the math.

Point dict shape: {"x": int, "y": int, "color": int, "rep_count": int}
- x, y in laser coords (-15000..15000)
- color packed as R | (G<<8) | (B<<16); 0 = blanked
- rep_count: 0 normal, 2 at sharp corners for dwell
"""

from __future__ import annotations

import math
from typing import List, Dict, Tuple

Point = Dict[str, int]
PointList = List[Point]

LASER_MAX = 15000

COLOR_NAMES = {
    "white":   0xFFFFFF,
    "red":     0x0000FF,  # R=255, G=0, B=0 → 0x0000FF in BGR packing
    "green":   0x00FF00,
    "blue":    0xFF0000,
    "yellow":  0x00FFFF,
    "cyan":    0xFFFF00,
    "magenta": 0xFF00FF,
    "orange":  0x0080FF,  # R=255, G=128, B=0
    "purple":  0xFF0080,  # R=128, G=0, B=255
    "pink":    0x8040FF,
}


def pack_rgb(r: int, g: int, b: int) -> int:
    """Pack RGB (each 0-255) into the uint32 color used by the SDK."""
    return (int(r) & 0xFF) | ((int(g) & 0xFF) << 8) | ((int(b) & 0xFF) << 16)


def resolve_color(color) -> int:
    """Accept a color name, 0xRRGGBB int, or [r,g,b] list and return packed uint32."""
    if isinstance(color, int):
        # Assume the int is already in our BGR packing
        return color
    if isinstance(color, str):
        name = color.lower().strip()
        if name in COLOR_NAMES:
            return COLOR_NAMES[name]
        if name.startswith("#"):
            name = name[1:]
        if len(name) == 6:
            try:
                r = int(name[0:2], 16)
                g = int(name[2:4], 16)
                b = int(name[4:6], 16)
                return pack_rgb(r, g, b)
            except ValueError:
                pass
    if isinstance(color, (list, tuple)) and len(color) == 3:
        return pack_rgb(*color)
    return COLOR_NAMES["white"]


def _pt(x: float, y: float, color: int, rep: int = 0) -> Point:
    return {
        "x": int(max(-LASER_MAX, min(LASER_MAX, x))),
        "y": int(max(-LASER_MAX, min(LASER_MAX, y))),
        "color": int(color),
        "rep_count": int(rep),
    }


def _blank_travel(pts: PointList, to_x: float, to_y: float) -> None:
    """Append 3 blanked points at (to_x, to_y) to let the galvo travel
    between disconnected shapes without lasing."""
    for _ in range(3):
        pts.append(_pt(to_x, to_y, 0, 0))


# ─────── Primitives ───────

def draw_circle(cx: float, cy: float, radius: float, color, segments: int = 60) -> PointList:
    """Circle centered at (cx, cy). Returns segments+1 points (closed)."""
    c = resolve_color(color)
    segments = max(16, min(200, int(segments)))
    pts: PointList = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        pts.append(_pt(cx + radius * math.cos(angle),
                       cy + radius * math.sin(angle), c))
    return pts


def draw_polygon(cx: float, cy: float, radius: float, sides: int, color,
                 rotation_deg: float = 0.0, points_per_edge: int = 10) -> PointList:
    """Regular n-gon. Vertices get rep_count=2 for corner dwell."""
    c = resolve_color(color)
    sides = max(3, min(24, int(sides)))
    points_per_edge = max(3, min(30, int(points_per_edge)))
    rot = math.radians(rotation_deg)

    vertices = [
        (cx + radius * math.cos(rot + 2 * math.pi * i / sides),
         cy + radius * math.sin(rot + 2 * math.pi * i / sides))
        for i in range(sides)
    ]
    vertices.append(vertices[0])  # close

    pts: PointList = []
    for i in range(sides):
        ax, ay = vertices[i]
        bx, by = vertices[i + 1]
        for t in range(points_per_edge):
            f = t / points_per_edge
            x = ax + (bx - ax) * f
            y = ay + (by - ay) * f
            rep = 2 if t == 0 else 0  # dwell at each corner
            pts.append(_pt(x, y, c, rep))
    pts.append(_pt(vertices[0][0], vertices[0][1], c, 2))
    return pts


def draw_star(cx: float, cy: float, outer_r: float, points: int, color,
              inner_ratio: float = 0.4, rotation_deg: float = -90.0,
              points_per_edge: int = 8) -> PointList:
    """N-point star. inner_ratio controls pointiness (0.3-0.5 typical)."""
    c = resolve_color(color)
    points = max(3, min(20, int(points)))
    inner_r = outer_r * max(0.1, min(0.9, inner_ratio))
    rot = math.radians(rotation_deg)

    vertices: List[Tuple[float, float]] = []
    for i in range(points * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = rot + math.pi * i / points
        vertices.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    vertices.append(vertices[0])

    pts: PointList = []
    for i in range(len(vertices) - 1):
        ax, ay = vertices[i]
        bx, by = vertices[i + 1]
        for t in range(points_per_edge):
            f = t / points_per_edge
            pts.append(_pt(ax + (bx - ax) * f, ay + (by - ay) * f, c,
                           2 if t == 0 else 0))
    pts.append(_pt(vertices[0][0], vertices[0][1], c, 2))
    return pts


def draw_line(x1: float, y1: float, x2: float, y2: float, color,
              samples: int = 20) -> PointList:
    """Straight line from A to B."""
    c = resolve_color(color)
    samples = max(2, min(200, int(samples)))
    return [
        _pt(x1 + (x2 - x1) * i / (samples - 1),
            y1 + (y2 - y1) * i / (samples - 1), c)
        for i in range(samples)
    ]


def draw_rectangle(cx: float, cy: float, width: float, height: float, color,
                   rotation_deg: float = 0.0, points_per_edge: int = 12) -> PointList:
    """Axis-aligned or rotated rectangle."""
    c = resolve_color(color)
    hw, hh = width / 2, height / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (-hw, -hh)]
    rot = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    world = [(cx + x * cos_r - y * sin_r, cy + x * sin_r + y * cos_r) for x, y in corners]

    pts: PointList = []
    for i in range(4):
        ax, ay = world[i]
        bx, by = world[i + 1]
        for t in range(points_per_edge):
            f = t / points_per_edge
            pts.append(_pt(ax + (bx - ax) * f, ay + (by - ay) * f, c,
                           2 if t == 0 else 0))
    pts.append(_pt(world[0][0], world[0][1], c, 2))
    return pts


def draw_spiral(cx: float, cy: float, max_radius: float, color,
                turns: float = 3.0, samples: int = 200) -> PointList:
    """Archimedean spiral from center outward."""
    c = resolve_color(color)
    turns = max(0.5, min(20, float(turns)))
    samples = max(30, min(800, int(samples)))
    pts: PointList = []
    for i in range(samples):
        f = i / (samples - 1)
        angle = 2 * math.pi * turns * f
        r = max_radius * f
        pts.append(_pt(cx + r * math.cos(angle), cy + r * math.sin(angle), c))
    return pts


# ─────── Stroke font ───────
# Each glyph is a list of strokes. Each stroke is a list of (x, y) points on a
# unit square where x ∈ [0, 1] and y ∈ [0, 1] (origin bottom-left).
# A new stroke means "lift the beam (blank) then continue".

_GLYPHS: Dict[str, List[List[Tuple[float, float]]]] = {
    "0": [[(0.2, 0.2), (0.2, 0.8), (0.8, 0.8), (0.8, 0.2), (0.2, 0.2)]],
    "1": [[(0.3, 0.7), (0.5, 0.95), (0.5, 0.05)], [(0.3, 0.05), (0.7, 0.05)]],
    "2": [[(0.2, 0.8), (0.5, 0.95), (0.8, 0.8), (0.8, 0.6),
           (0.2, 0.1), (0.8, 0.1)]],
    "3": [[(0.2, 0.85), (0.7, 0.95), (0.8, 0.75), (0.55, 0.55),
           (0.2, 0.55)], [(0.55, 0.55), (0.8, 0.35), (0.7, 0.1),
           (0.2, 0.15)]],
    "4": [[(0.2, 0.95), (0.2, 0.55), (0.85, 0.55)], [(0.75, 0.95), (0.75, 0.05)]],
    "5": [[(0.8, 0.95), (0.25, 0.95), (0.2, 0.55), (0.7, 0.55),
           (0.8, 0.3), (0.55, 0.05), (0.2, 0.1)]],
    "6": [[(0.8, 0.9), (0.4, 0.9), (0.2, 0.55), (0.2, 0.2),
           (0.55, 0.05), (0.8, 0.3), (0.75, 0.5), (0.25, 0.5)]],
    "7": [[(0.2, 0.95), (0.8, 0.95), (0.4, 0.05)]],
    "8": [[(0.2, 0.3), (0.2, 0.1), (0.8, 0.1), (0.8, 0.3),
           (0.2, 0.55), (0.2, 0.8), (0.8, 0.8), (0.8, 0.55),
           (0.2, 0.3)]],
    "9": [[(0.8, 0.55), (0.2, 0.55), (0.2, 0.8), (0.6, 0.95),
           (0.8, 0.8), (0.8, 0.2), (0.4, 0.05)]],
    " ": [],
    ".": [[(0.4, 0.1), (0.5, 0.15), (0.5, 0.05), (0.4, 0.1)]],
    "-": [[(0.2, 0.5), (0.8, 0.5)]],
    "!": [[(0.5, 0.95), (0.5, 0.3)], [(0.5, 0.15), (0.5, 0.05)]],
    "A": [[(0.1, 0.05), (0.5, 0.95), (0.9, 0.05)], [(0.25, 0.45), (0.75, 0.45)]],
    "B": [[(0.2, 0.05), (0.2, 0.95), (0.7, 0.95), (0.85, 0.75),
           (0.65, 0.55), (0.2, 0.55)], [(0.65, 0.55), (0.85, 0.35),
           (0.7, 0.05), (0.2, 0.05)]],
    "C": [[(0.85, 0.85), (0.25, 0.95), (0.15, 0.5), (0.25, 0.05), (0.85, 0.15)]],
    "D": [[(0.2, 0.05), (0.2, 0.95), (0.65, 0.95), (0.85, 0.5),
           (0.65, 0.05), (0.2, 0.05)]],
    "E": [[(0.85, 0.95), (0.2, 0.95), (0.2, 0.05), (0.85, 0.05)],
          [(0.2, 0.5), (0.7, 0.5)]],
    "F": [[(0.85, 0.95), (0.2, 0.95), (0.2, 0.05)],
          [(0.2, 0.5), (0.65, 0.5)]],
    "G": [[(0.85, 0.85), (0.25, 0.95), (0.15, 0.5), (0.25, 0.05),
           (0.85, 0.15), (0.85, 0.5), (0.55, 0.5)]],
    "H": [[(0.2, 0.95), (0.2, 0.05)], [(0.2, 0.5), (0.8, 0.5)],
          [(0.8, 0.95), (0.8, 0.05)]],
    "I": [[(0.2, 0.95), (0.8, 0.95)], [(0.5, 0.95), (0.5, 0.05)],
          [(0.2, 0.05), (0.8, 0.05)]],
    "L": [[(0.2, 0.95), (0.2, 0.05), (0.85, 0.05)]],
    "M": [[(0.15, 0.05), (0.15, 0.95), (0.5, 0.5), (0.85, 0.95), (0.85, 0.05)]],
    "N": [[(0.2, 0.05), (0.2, 0.95), (0.8, 0.05), (0.8, 0.95)]],
    "O": [[(0.2, 0.5), (0.35, 0.95), (0.65, 0.95), (0.8, 0.5),
           (0.65, 0.05), (0.35, 0.05), (0.2, 0.5)]],
    "P": [[(0.2, 0.05), (0.2, 0.95), (0.7, 0.95), (0.85, 0.75),
           (0.7, 0.55), (0.2, 0.55)]],
    "R": [[(0.2, 0.05), (0.2, 0.95), (0.7, 0.95), (0.85, 0.75),
           (0.7, 0.55), (0.2, 0.55)], [(0.5, 0.55), (0.85, 0.05)]],
    "S": [[(0.85, 0.85), (0.65, 0.95), (0.25, 0.9), (0.2, 0.65),
           (0.35, 0.55), (0.7, 0.5), (0.85, 0.35), (0.8, 0.15),
           (0.35, 0.05), (0.15, 0.15)]],
    "T": [[(0.1, 0.95), (0.9, 0.95)], [(0.5, 0.95), (0.5, 0.05)]],
    "U": [[(0.2, 0.95), (0.2, 0.25), (0.35, 0.05), (0.65, 0.05),
           (0.8, 0.25), (0.8, 0.95)]],
    "V": [[(0.1, 0.95), (0.5, 0.05), (0.9, 0.95)]],
    "W": [[(0.1, 0.95), (0.3, 0.05), (0.5, 0.6), (0.7, 0.05), (0.9, 0.95)]],
    "X": [[(0.15, 0.95), (0.85, 0.05)], [(0.85, 0.95), (0.15, 0.05)]],
    "Y": [[(0.15, 0.95), (0.5, 0.55)], [(0.85, 0.95), (0.5, 0.55), (0.5, 0.05)]],
    "Z": [[(0.2, 0.95), (0.85, 0.95), (0.15, 0.05), (0.85, 0.05)]],
}


def draw_text(text: str, cx: float, cy: float, size: float, color,
              points_per_stroke: int = 12) -> PointList:
    """Draw uppercase text with a simple stroke font. Unknown chars render as space.

    `size` is the total height of one glyph in laser units. Width is
    proportional with spacing between chars.
    """
    c = resolve_color(color)
    text = text.upper()
    char_h = size
    char_w = size * 0.7
    spacing = size * 0.2
    total_w = len(text) * char_w + max(0, len(text) - 1) * spacing
    x0 = cx - total_w / 2
    y0 = cy - char_h / 2

    pts: PointList = []
    pen_x = x0
    for ch in text:
        glyph = _GLYPHS.get(ch, _GLYPHS[" "])
        for stroke in glyph:
            if not stroke:
                continue
            # Blank travel to stroke start (including from previous glyph)
            fx = pen_x + stroke[0][0] * char_w
            fy = y0 + stroke[0][1] * char_h
            if pts:
                for _ in range(3):
                    pts.append(_pt(fx, fy, 0, 0))
            # Draw each segment of the stroke with interpolation
            for i in range(len(stroke) - 1):
                ax = pen_x + stroke[i][0] * char_w
                ay = y0 + stroke[i][1] * char_h
                bx = pen_x + stroke[i + 1][0] * char_w
                by = y0 + stroke[i + 1][1] * char_h
                for t in range(points_per_stroke):
                    f = t / points_per_stroke
                    pts.append(_pt(ax + (bx - ax) * f, ay + (by - ay) * f, c))
            # Emit the endpoint of the final segment too
            ex = pen_x + stroke[-1][0] * char_w
            ey = y0 + stroke[-1][1] * char_h
            pts.append(_pt(ex, ey, c))
        pen_x += char_w + spacing

    return pts


def draw_heart(cx: float, cy: float, size: float, color,
               samples: int = 80) -> PointList:
    """Parametric heart curve."""
    c = resolve_color(color)
    s = size / 16.0
    pts: PointList = []
    for i in range(samples + 1):
        t = 2 * math.pi * i / samples
        x = 16 * (math.sin(t) ** 3)
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append(_pt(cx + x * s, cy + y * s, c))
    return pts


# ─────── Composition ───────

def compose(shapes: List[PointList]) -> PointList:
    """Join multiple shape point-lists with blanked travel between them."""
    if not shapes:
        return []
    out: PointList = list(shapes[0])
    for shape in shapes[1:]:
        if not shape:
            continue
        first = shape[0]
        _blank_travel(out, first["x"], first["y"])
        out.extend(shape)
    return out
