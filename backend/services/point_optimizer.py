"""Stage 8: Point optimization for laser output.

Applied per-frame:
1. Corner dwell — duplicate points at sharp corners
2. Blanking insertion — extra blanking points at transitions
3. Point count enforcement — target 200-800 based on path length
"""
import math
import logging
from typing import List
from models.laser_types import LaserFrame, LaserPoint

logger = logging.getLogger(__name__)

# Constants
MIN_POINTS = 200
MAX_POINTS = 800
LENGTH_LOW = 10000
LENGTH_HIGH = 80000
CORNER_THRESHOLD_DEG = 90.0
DWELL_POINTS = 2
BLANKING_POINTS = 3


def optimize_frame(points: List[LaserPoint], max_points: int = MAX_POINTS) -> List[LaserPoint]:
    """Full optimization pipeline for a frame's points."""
    if not points:
        return points
    
    # Step 1: Corner dwell
    points = add_corner_dwell(points)
    
    # Step 2: Blanking insertion
    points = insert_blanking(points)
    
    # Step 3: Point count enforcement
    points = enforce_point_count(points, max_points)
    
    return points


def add_corner_dwell(points: List[LaserPoint]) -> List[LaserPoint]:
    """Add extra dwell points at sharp corners (angle < 90 degrees)."""
    if len(points) < 3:
        return points
    
    result = [points[0]]
    
    for i in range(1, len(points) - 1):
        p_prev = points[i - 1]
        p_curr = points[i]
        p_next = points[i + 1]
        
        result.append(p_curr)
        
        # Only check visible (non-blanked) consecutive points
        if not p_prev.blanked and not p_curr.blanked and not p_next.blanked:
            angle = _compute_angle(p_prev, p_curr, p_next)
            if angle < CORNER_THRESHOLD_DEG:
                # Add dwell points
                for _ in range(DWELL_POINTS):
                    result.append(LaserPoint(
                        x=p_curr.x, y=p_curr.y,
                        r=p_curr.r, g=p_curr.g, b=p_curr.b,
                        blanked=False
                    ))
    
    result.append(points[-1])
    return result


def insert_blanking(points: List[LaserPoint]) -> List[LaserPoint]:
    """Insert extra blanking points at visible-to-blank transitions."""
    if len(points) < 2:
        return points
    
    result = [points[0]]
    
    for i in range(1, len(points)):
        prev = points[i - 1]
        curr = points[i]
        
        if not prev.blanked and curr.blanked:
            # Visible → Blank: add blanking at last visible position
            for _ in range(BLANKING_POINTS):
                result.append(LaserPoint(
                    x=prev.x, y=prev.y,
                    r=0, g=0, b=0, blanked=True
                ))
        elif prev.blanked and not curr.blanked:
            # Blank → Visible: add blanking at new visible position
            for _ in range(BLANKING_POINTS):
                result.append(LaserPoint(
                    x=curr.x, y=curr.y,
                    r=0, g=0, b=0, blanked=True
                ))
        
        result.append(curr)
    
    return result


def enforce_point_count(points: List[LaserPoint], max_points: int = MAX_POINTS) -> List[LaserPoint]:
    """Enforce target point count based on total path length."""
    if not points:
        return points
    
    path_length = _compute_path_length(points)
    
    # Determine target
    if path_length <= LENGTH_LOW:
        target = MIN_POINTS
    elif path_length >= LENGTH_HIGH:
        target = max_points
    else:
        # Linear interpolation
        frac = (path_length - LENGTH_LOW) / (LENGTH_HIGH - LENGTH_LOW)
        target = int(MIN_POINTS + frac * (max_points - MIN_POINTS))
    
    current = len(points)
    
    if current < target:
        return interpolate_points(points, target)
    elif current > target:
        return downsample_points(points, target)
    
    return points


def interpolate_points(points: List[LaserPoint], target: int) -> List[LaserPoint]:
    """Add extra points along segments proportional to segment length."""
    if len(points) < 2 or target <= len(points):
        return points
    
    extra_needed = target - len(points)
    
    # Calculate segment lengths
    segments = []
    for i in range(len(points) - 1):
        dist = _distance(points[i], points[i + 1])
        segments.append(dist)
    
    total_length = sum(segments)
    if total_length == 0:
        return points
    
    # Allocate extra points proportional to segment length
    result = []
    for i in range(len(points) - 1):
        result.append(points[i])
        
        if segments[i] > 0:
            # How many extra points for this segment
            extra_for_segment = int(extra_needed * segments[i] / total_length)
            if extra_for_segment > 0:
                p1 = points[i]
                p2 = points[i + 1]
                for j in range(1, extra_for_segment + 1):
                    frac = j / (extra_for_segment + 1)
                    interp = LaserPoint(
                        x=int(p1.x + (p2.x - p1.x) * frac),
                        y=int(p1.y + (p2.y - p1.y) * frac),
                        r=p1.r if not p1.blanked else p2.r,
                        g=p1.g if not p1.blanked else p2.g,
                        b=p1.b if not p1.blanked else p2.b,
                        blanked=p1.blanked or p2.blanked,
                    )
                    result.append(interp)
    
    result.append(points[-1])
    return result


def downsample_points(points: List[LaserPoint], target: int) -> List[LaserPoint]:
    """Uniformly sample visible points while preserving blanking points."""
    if len(points) <= target:
        return points
    
    # Separate blanking and visible points with their indices
    blanking = [(i, p) for i, p in enumerate(points) if p.blanked]
    visible = [(i, p) for i, p in enumerate(points) if not p.blanked]
    
    # Must keep all blanking points + first and last visible
    blanking_count = len(blanking)
    visible_budget = max(2, target - blanking_count)
    
    if len(visible) <= visible_budget:
        return points
    
    # Uniformly sample visible points, always keeping first and last
    step = max(1, (len(visible) - 1) / (visible_budget - 1))
    sampled_visible = []
    for i in range(visible_budget):
        idx = min(int(i * step), len(visible) - 1)
        sampled_visible.append(visible[idx])
    
    # Merge and sort by original index
    merged = blanking + sampled_visible
    merged.sort(key=lambda x: x[0])
    
    return [p for _, p in merged]


def _compute_angle(p1: LaserPoint, p2: LaserPoint, p3: LaserPoint) -> float:
    """Compute the angle at p2 formed by p1-p2-p3, in degrees."""
    dx1 = p1.x - p2.x
    dy1 = p1.y - p2.y
    dx2 = p3.x - p2.x
    dy2 = p3.y - p2.y
    
    dot = dx1 * dx2 + dy1 * dy2
    mag1 = math.sqrt(dx1*dx1 + dy1*dy1)
    mag2 = math.sqrt(dx2*dx2 + dy2*dy2)
    
    if mag1 == 0 or mag2 == 0:
        return 180.0
    
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def _compute_path_length(points: List[LaserPoint]) -> float:
    """Sum of Euclidean distances between consecutive points."""
    total = 0.0
    for i in range(len(points) - 1):
        total += _distance(points[i], points[i + 1])
    return total


def _distance(p1: LaserPoint, p2: LaserPoint) -> float:
    """Euclidean distance between two points."""
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    return math.sqrt(dx*dx + dy*dy)
