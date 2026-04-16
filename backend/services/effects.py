"""Stage 6: Geometric effects for instrumental/non-lyric sections.
All functions return list[LaserPoint].
"""
import math
import logging
from typing import List, Tuple
from models.laser_types import LaserPoint

logger = logging.getLogger(__name__)


def lissajous(
    timestamp_ms: float,
    color: Tuple[int, int, int],
    energy: float = 1.0,
    radius: int = 20000,
    num_points: int = 200,
    a: int = 3,
    b: int = 2
) -> List[LaserPoint]:
    """Lissajous curve: x = sin(a*t + delta), y = sin(b*t)."""
    delta = timestamp_ms / 1000.0  # slowly rotating phase
    r, g, bb = color
    points = []
    
    for i in range(num_points):
        t = 2 * math.pi * i / num_points
        x = int(radius * math.sin(a * t + delta))
        y = int(radius * math.sin(b * t))
        x = max(-32768, min(32767, x))
        y = max(-32768, min(32767, y))
        
        if i == 0:
            # Blanking move to start
            points.append(LaserPoint(x=x, y=y, r=0, g=0, b=0, blanked=True))
            points.append(LaserPoint(x=x, y=y, r=r, g=g, b=bb, blanked=False))
        else:
            points.append(LaserPoint(x=x, y=y, r=r, g=g, b=bb, blanked=False))
    
    return points


def spiral(
    timestamp_ms: float,
    color: Tuple[int, int, int],
    energy: float = 1.0,
    num_points: int = 150,
    turns: float = 3.0
) -> List[LaserPoint]:
    """Archimedes spiral with energy-based radius."""
    max_radius = int(15000 + 10000 * energy)
    rotation = timestamp_ms / 500.0
    r, g, bb = color
    points = []
    
    for i in range(num_points):
        fraction = i / max(1, num_points - 1)
        angle = turns * 2 * math.pi * fraction + rotation
        radius = max_radius * fraction
        
        x = int(radius * math.cos(angle))
        y = int(radius * math.sin(angle))
        x = max(-32768, min(32767, x))
        y = max(-32768, min(32767, y))
        
        # Color intensity: dim at center, full at edge
        intensity = 0.3 + 0.7 * fraction
        cr = int(r * intensity)
        cg = int(g * intensity)
        cb = int(bb * intensity)
        
        if i == 0:
            points.append(LaserPoint(x=x, y=y, r=0, g=0, b=0, blanked=True))
            points.append(LaserPoint(x=x, y=y, r=cr, g=cg, b=cb, blanked=False))
        else:
            points.append(LaserPoint(x=x, y=y, r=cr, g=cg, b=cb, blanked=False))
    
    return points


def beam_fan(
    timestamp_ms: float,
    color: Tuple[int, int, int],
    energy: float = 1.0,
    radius: int = 28000,
    points_per_beam: int = 15
) -> List[LaserPoint]:
    """Radial lines from center, rotating. Beam count scales with energy."""
    num_beams = max(4, int(12 * energy))
    rotation = timestamp_ms / 800.0
    r, g, bb = color
    points = []
    
    for beam_idx in range(num_beams):
        angle = 2 * math.pi * beam_idx / num_beams + rotation
        
        # Blanking move back to center
        points.append(LaserPoint(x=0, y=0, r=0, g=0, b=0, blanked=True))
        points.append(LaserPoint(x=0, y=0, r=r, g=g, b=bb, blanked=False))
        points.append(LaserPoint(x=0, y=0, r=r, g=g, b=bb, blanked=False))
        
        # Draw beam outward
        for j in range(points_per_beam):
            frac = (j + 1) / points_per_beam
            x = int(radius * frac * math.cos(angle))
            y = int(radius * frac * math.sin(angle))
            x = max(-32768, min(32767, x))
            y = max(-32768, min(32767, y))
            points.append(LaserPoint(x=x, y=y, r=r, g=g, b=bb, blanked=False))
    
    return points


def starburst(
    timestamp_ms: float,
    beat_time_ms: float,
    color: Tuple[int, int, int],
    energy: float = 1.0,
    num_rays: int = 12,
    max_radius: int = 25000,
    duration_ms: float = 500.0,
    points_per_ray: int = 10
) -> List[LaserPoint]:
    """Beat-triggered starburst explosion."""
    elapsed = timestamp_ms - beat_time_ms
    if elapsed < 0 or elapsed > duration_ms:
        return []
    
    progress = elapsed / duration_ms
    fade = 1.0 - progress  # Fades out
    current_radius = int(max_radius * progress)
    
    r, g, bb = color
    cr = int(r * fade)
    cg = int(g * fade)
    cb = int(bb * fade)
    
    points = []
    for ray_idx in range(num_rays):
        angle = 2 * math.pi * ray_idx / num_rays
        
        points.append(LaserPoint(x=0, y=0, r=0, g=0, b=0, blanked=True))
        points.append(LaserPoint(x=0, y=0, r=cr, g=cg, b=cb, blanked=False))
        
        for j in range(points_per_ray):
            frac = (j + 1) / points_per_ray
            x = int(current_radius * frac * math.cos(angle))
            y = int(current_radius * frac * math.sin(angle))
            x = max(-32768, min(32767, x))
            y = max(-32768, min(32767, y))
            points.append(LaserPoint(x=x, y=y, r=cr, g=cg, b=cb, blanked=False))
    
    return points


def tunnel(
    timestamp_ms: float,
    color: Tuple[int, int, int],
    energy: float = 1.0,
    max_radius: int = 25000,
    num_rings: int = 5,
    points_per_side: int = 8
) -> List[LaserPoint]:
    """Concentric squares creating depth illusion, moving inward."""
    phase = timestamp_ms / 1000.0
    r, g, bb = color
    points = []
    
    for ring_idx in range(num_rings):
        ring_phase = (ring_idx / num_rings + phase) % 1.0
        radius = int(max_radius * ring_phase)
        
        if radius < 1000:
            continue
        
        brightness = ring_phase  # Brighter as it grows
        cr = int(r * brightness)
        cg = int(g * brightness)
        cb = int(bb * brightness)
        
        # Draw a square
        corners = [
            (-radius, -radius),
            (radius, -radius),
            (radius, radius),
            (-radius, radius),
            (-radius, -radius),  # close
        ]
        
        # Blanking move to first corner
        cx, cy = corners[0]
        cx = max(-32768, min(32767, cx))
        cy = max(-32768, min(32767, cy))
        points.append(LaserPoint(x=cx, y=cy, r=0, g=0, b=0, blanked=True))
        points.append(LaserPoint(x=cx, y=cy, r=cr, g=cg, b=cb, blanked=False))
        points.append(LaserPoint(x=cx, y=cy, r=cr, g=cg, b=cb, blanked=False))
        
        for i in range(len(corners) - 1):
            x1, y1 = corners[i]
            x2, y2 = corners[i + 1]
            for j in range(1, points_per_side + 1):
                frac = j / points_per_side
                x = int(x1 + (x2 - x1) * frac)
                y = int(y1 + (y2 - y1) * frac)
                x = max(-32768, min(32767, x))
                y = max(-32768, min(32767, y))
                points.append(LaserPoint(x=x, y=y, r=cr, g=cg, b=cb, blanked=False))
    
    return points


def beat_pulse(
    timestamp_ms: float,
    beat_times_ms: List[float],
    color: Tuple[int, int, int],
    base_radius: int = 3000,
    pulse_radius: int = 8000,
    decay_ms: float = 200.0,
    num_points: int = 48
) -> List[LaserPoint]:
    """Pulsing circle synced to beats."""
    # Find most recent beat
    pulse = 0.0
    for bt in beat_times_ms:
        elapsed = timestamp_ms - bt
        if 0 <= elapsed < decay_ms:
            pulse = max(pulse, 1.0 - elapsed / decay_ms)
    
    radius = base_radius + int(pulse_radius * pulse)
    r, g, bb = color
    points = []
    
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        x = int(radius * math.cos(angle))
        y = int(radius * math.sin(angle))
        x = max(-32768, min(32767, x))
        y = max(-32768, min(32767, y))
        
        if i == 0:
            points.append(LaserPoint(x=x, y=y, r=0, g=0, b=0, blanked=True))
            points.append(LaserPoint(x=x, y=y, r=r, g=g, b=bb, blanked=False))
        else:
            points.append(LaserPoint(x=x, y=y, r=r, g=g, b=bb, blanked=False))
    
    # Close circle
    if points:
        first_vis = next((p for p in points if not p.blanked), None)
        if first_vis:
            points.append(LaserPoint(x=first_vis.x, y=first_vis.y, r=r, g=g, b=bb, blanked=False))
    
    return points
