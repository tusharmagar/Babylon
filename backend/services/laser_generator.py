"""Stage 7: Frame generation at 30fps.

Composes text rendering and geometric effects into LaserFrames
based on the show design, lyrics, and audio analysis.
"""
import logging
from typing import List, Optional
from models.laser_types import (
    LaserFrame, LaserPoint, SyncedLine, SyncedWord,
    SongSection, ShowDesign
)
from services.text_renderer import text_to_points, animated_text_frame
from services import effects

logger = logging.getLogger(__name__)

FPS = 30
FRAME_DURATION_MS = 1000.0 / FPS  # 33.33ms


def generate_show(
    lyrics: List[SyncedLine],
    design: ShowDesign,
    analysis: dict,
    on_progress=None
) -> List[LaserFrame]:
    """Generate the complete laser show as a list of LaserFrames.
    
    For each frame at timestamp_ms:
    1. Find active section
    2. Find active lyric line
    3. Get energy level
    4. Render text or geometric effect
    """
    duration_ms = analysis.get('duration_ms', 0)
    if duration_ms <= 0:
        return []
    
    total_frames = int(duration_ms / FRAME_DURATION_MS) + 1
    sections = design.sections
    palette = design.color_palette or [(0, 255, 100)]
    section_effects = design.section_effects or {}
    text_style = design.text_style or "typewriter"
    energy_envelope = analysis.get('energy_envelope', [])
    beat_times_ms = analysis.get('beat_times_ms', [])
    
    frames = []
    
    logger.info(f"Generating {total_frames} frames at {FPS}fps ({duration_ms/1000:.1f}s)")
    
    for frame_idx in range(total_frames):
        timestamp_ms = frame_idx * FRAME_DURATION_MS
        
        # 1. Find active section
        active_section = _find_active_section(sections, timestamp_ms)
        section_idx = sections.index(active_section) if active_section in sections else 0
        
        # 2. Find active lyric line
        active_line = _find_active_line(lyrics, timestamp_ms)
        
        # 3. Get current energy
        energy = _interpolate_energy(energy_envelope, timestamp_ms)
        
        # 4. Get section color (cycle through palette)
        color = palette[section_idx % len(palette)]
        
        # 5. Get effect type
        effect_type = ""
        if active_section:
            effect_type = section_effects.get(active_section.label, "")
        
        # 6. Render frame
        points = _render_frame(
            timestamp_ms=timestamp_ms,
            active_line=active_line,
            active_section=active_section,
            effect_type=effect_type,
            text_style=text_style,
            color=color,
            energy=energy,
            beat_times_ms=beat_times_ms,
        )
        
        frames.append(LaserFrame(points=points, timestamp_ms=timestamp_ms))
        
        # Progress callback
        if on_progress and frame_idx % 100 == 0:
            on_progress(frame_idx / total_frames)
    
    logger.info(f"Generated {len(frames)} frames")
    return frames


def _find_active_section(sections: List[SongSection], timestamp_ms: float) -> Optional[SongSection]:
    """Find the section active at the given timestamp."""
    for section in sections:
        if section.start_ms <= timestamp_ms < section.end_ms:
            return section
    # Default: return last section or create a default
    if sections:
        return sections[-1]
    return SongSection(label="instrumental", start_ms=0, end_ms=999999, energy=0.5)


def _find_active_line(lyrics: List[SyncedLine], timestamp_ms: float) -> Optional[SyncedLine]:
    """Find the lyric line active at the given timestamp."""
    for line in lyrics:
        if line.start_ms <= timestamp_ms < line.end_ms:
            return line
    return None


def _interpolate_energy(energy_envelope: list, timestamp_ms: float) -> float:
    """Interpolate energy from the envelope at the given timestamp."""
    if not energy_envelope:
        return 0.5
    
    # Find surrounding samples
    for i in range(len(energy_envelope) - 1):
        t0 = energy_envelope[i]['time_ms']
        t1 = energy_envelope[i + 1]['time_ms']
        if t0 <= timestamp_ms <= t1:
            if t1 == t0:
                return energy_envelope[i]['energy']
            frac = (timestamp_ms - t0) / (t1 - t0)
            e0 = energy_envelope[i]['energy']
            e1 = energy_envelope[i + 1]['energy']
            return e0 + frac * (e1 - e0)
    
    # Return last or first
    if timestamp_ms >= energy_envelope[-1]['time_ms']:
        return energy_envelope[-1]['energy']
    return energy_envelope[0]['energy']


def _render_frame(
    timestamp_ms: float,
    active_line: Optional[SyncedLine],
    active_section: Optional[SongSection],
    effect_type: str,
    text_style: str,
    color: tuple,
    energy: float,
    beat_times_ms: list,
) -> List[LaserPoint]:
    """Render a single frame's points."""
    
    if active_line and active_line.text.strip():
        # Has lyrics — render text
        line_duration = active_line.end_ms - active_line.start_ms
        if line_duration <= 0:
            line_duration = 2000
        line_progress = (timestamp_ms - active_line.start_ms) / line_duration
        line_progress = max(0.0, min(1.0, line_progress))
        
        # Check for word-level timing
        if active_line.words:
            active_word = _find_active_word(active_line.words, timestamp_ms)
            if active_word:
                # Render only the active word at large scale
                word_duration = active_word.end_ms - active_word.start_ms
                if word_duration <= 0:
                    word_duration = 500
                word_progress = (timestamp_ms - active_word.start_ms) / word_duration
                word_progress = max(0.0, min(1.0, word_progress))
                
                # Brightness fades: 1.0 - 0.3 * word_progress
                brightness = 1.0 - 0.3 * word_progress
                faded_color = (
                    int(color[0] * brightness),
                    int(color[1] * brightness),
                    int(color[2] * brightness)
                )
                return text_to_points(
                    active_word.word,
                    center_x=0, center_y=0,
                    scale=1500.0,
                    color=faded_color
                )
        
        # No word timing — render full line
        # Use the text style from design
        actual_style = text_style
        if effect_type and effect_type.startswith("text_"):
            actual_style = effect_type.replace("text_", "")
        
        return animated_text_frame(
            text=active_line.text,
            progress=line_progress,
            style=actual_style,
            color=color,
            center_x=0, center_y=0,
            scale=1200.0
        )
    
    else:
        # No lyrics — instrumental section, generate geometric effect
        energy_scale = 0.5 + 0.5 * energy
        scaled_color = (
            int(color[0] * energy_scale),
            int(color[1] * energy_scale),
            int(color[2] * energy_scale)
        )
        
        if effect_type == "lissajous":
            return effects.lissajous(timestamp_ms, scaled_color, energy)
        elif effect_type == "spiral":
            return effects.spiral(timestamp_ms, scaled_color, energy)
        elif effect_type == "beam_fan":
            return effects.beam_fan(timestamp_ms, scaled_color, energy)
        elif effect_type == "starburst":
            # Find nearest beat
            nearest_beat = _find_nearest_beat(beat_times_ms, timestamp_ms)
            if nearest_beat is not None:
                pts = effects.starburst(timestamp_ms, nearest_beat, scaled_color, energy)
                if pts:
                    return pts
            return effects.beam_fan(timestamp_ms, scaled_color, energy)
        elif effect_type == "tunnel":
            return effects.tunnel(timestamp_ms, scaled_color, energy)
        else:
            # Default: beat pulse + lissajous
            pts = effects.lissajous(timestamp_ms, scaled_color, energy)
            pulse_pts = effects.beat_pulse(timestamp_ms, beat_times_ms, scaled_color)
            return pts + pulse_pts


def _find_active_word(words: List[SyncedWord], timestamp_ms: float) -> Optional[SyncedWord]:
    """Find the word active at the given timestamp."""
    for word in words:
        if word.start_ms <= timestamp_ms < word.end_ms:
            return word
    return None


def _find_nearest_beat(beat_times_ms: list, timestamp_ms: float) -> Optional[float]:
    """Find the nearest beat time before the current timestamp."""
    nearest = None
    for bt in beat_times_ms:
        if bt <= timestamp_ms:
            if nearest is None or bt > nearest:
                nearest = bt
        else:
            break
    return nearest
