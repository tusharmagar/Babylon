"""Stage 4: AI Show Design using OpenAI GPT-4o.
Falls back to rule-based design if unavailable.
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from typing import List, Tuple

from models.laser_types import ShowDesign, SongSection, SyncedLine

_DEFAULT_PALETTE: List[Tuple[int, int, int]] = [
    (0, 255, 100), (255, 0, 200), (0, 150, 255), (255, 255, 0),
]


def _normalize_palette(raw) -> List[Tuple[int, int, int]]:
    """Coerce whatever the LLM returned into List[(r,g,b)] of ints in 0-255.

    LLMs occasionally emit [[[r,g,b], [r,g,b]]] (one extra nesting level) or
    entries of the wrong length/type. Normalizing here prevents downstream
    `TypeError: can't multiply sequence by non-int` in laser_generator.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        return list(_DEFAULT_PALETTE)

    items = list(raw)
    # Unwrap one level of nesting if it looks like [[[r,g,b], ...]]
    if (
        len(items) == 1
        and isinstance(items[0], (list, tuple))
        and items[0]
        and isinstance(items[0][0], (list, tuple))
    ):
        items = list(items[0])

    out: List[Tuple[int, int, int]] = []
    for entry in items:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            continue
        r, g, b = entry
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (r, g, b)):
            continue
        out.append((
            max(0, min(255, int(r))),
            max(0, min(255, int(g))),
            max(0, min(255, int(b))),
        ))

    return out if out else list(_DEFAULT_PALETTE)

logger = logging.getLogger(__name__)

SHOW_DESIGN_PROMPT = """You are a laser show designer. Given song lyrics, audio analysis data, and song metadata, create a creative laser show design.

Return a JSON object with:
{
  "color_palette": [[r,g,b], ...],  // 3-5 RGB colors (0-255) that match the song mood
  "sections": [  // Song sections
    {"label": "intro|verse|chorus|bridge|instrumental|outro|buildup|drop", 
     "start_ms": float, "end_ms": float, "energy": float}
  ],
  "section_effects": {  // Map section labels to effects
    "intro": "tunnel",
    "verse": "text_typewriter", 
    "chorus": "text_wave",
    "bridge": "text_fade",
    "instrumental": "lissajous",
    "outro": "spiral"
  },
  "text_style": "typewriter|fade|wave|word_highlight",
  "intensity_curve": "build|steady|dynamic"
}

Effect types for lyric sections: text_typewriter, text_fade, text_wave, text_highlight
Effect types for instrumental sections: lissajous, spiral, beam_fan, tunnel, starburst

Use the segment boundaries and energy data to determine section boundaries.
Match energy levels to section types (chorus = high energy, verse = medium, bridge = low).
Create a visually dynamic show that follows the emotional arc of the song."""


async def design_show(
    lyrics: List[SyncedLine],
    audio_analysis: dict,
    title: str,
    artist: str
) -> ShowDesign:
    """Use GPT-4o to create a show design, with rule-based fallback."""
    api_key = os.environ.get('OPENAI_API_KEY')
    
    if api_key:
        try:
            return await _ai_design(lyrics, audio_analysis, title, artist, api_key)
        except Exception as e:
            logger.warning(f"AI design failed, using fallback: {e}")
    else:
        logger.info("No OPENAI_API_KEY, using rule-based design")
    
    return _fallback_design(lyrics, audio_analysis)


async def _ai_design(
    lyrics: List[SyncedLine],
    audio_analysis: dict,
    title: str,
    artist: str,
    api_key: str
) -> ShowDesign:
    """Generate show design using GPT-4o."""
    client = AsyncOpenAI(api_key=api_key)
    
    # Prepare lyrics summary
    lyrics_text = "\n".join([f"[{line.start_ms/1000:.1f}s] {line.text}" for line in lyrics[:50]])
    
    user_msg = f"""Song: \"{title}\" by {artist}
BPM: {audio_analysis['bpm']:.0f}
Duration: {audio_analysis['duration_s']:.0f}s
Beat count: {len(audio_analysis['beat_times_ms'])}
Segment boundaries (ms): {audio_analysis['segment_boundaries_ms']}

Lyrics:
{lyrics_text}

Design a laser show for this song."""
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SHOW_DESIGN_PROMPT},
            {"role": "user", "content": user_msg}
        ],
        temperature=0.8,
        response_format={"type": "json_object"},
    )
    
    data = json.loads(response.choices[0].message.content)
    logger.info(f"AI show design: {len(data.get('sections', []))} sections, style={data.get('text_style')}")
    
    # Parse into ShowDesign
    palette = _normalize_palette(data.get('color_palette'))
    sections = [
        SongSection(
            label=s['label'],
            start_ms=float(s['start_ms']),
            end_ms=float(s['end_ms']),
            energy=float(s.get('energy', 0.5))
        )
        for s in data.get('sections', [])
    ]
    
    return ShowDesign(
        color_palette=palette,
        section_effects=data.get('section_effects', {}),
        text_style=data.get('text_style', 'typewriter'),
        intensity_curve=data.get('intensity_curve', 'dynamic'),
        bpm=audio_analysis['bpm'],
        sections=sections
    )


def _fallback_design(
    lyrics: List[SyncedLine],
    audio_analysis: dict
) -> ShowDesign:
    """Rule-based show design fallback."""
    palette = [(0, 255, 100), (255, 0, 200), (0, 150, 255), (255, 255, 0)]
    
    boundaries = audio_analysis.get('segment_boundaries_ms', [])
    duration_ms = audio_analysis.get('duration_ms', 0)
    energy_envelope = audio_analysis.get('energy_envelope', [])
    
    if len(boundaries) < 2:
        boundaries = [duration_ms * i / 8 for i in range(9)]
    
    # Label sections based on position and energy
    section_labels = ['intro', 'verse', 'chorus', 'verse', 'chorus', 'bridge', 'chorus', 'outro']
    
    sections = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else duration_ms
        label = section_labels[i % len(section_labels)]
        
        # Calculate average energy for this section
        section_energy = _avg_energy_in_range(energy_envelope, start, end)
        
        sections.append(SongSection(
            label=label,
            start_ms=start,
            end_ms=end,
            energy=section_energy
        ))
    
    section_effects = {
        'intro': 'tunnel',
        'verse': 'text_typewriter',
        'chorus': 'text_wave',
        'bridge': 'text_fade',
        'instrumental': 'lissajous',
        'outro': 'spiral',
        'buildup': 'beam_fan',
        'drop': 'starburst',
    }
    
    return ShowDesign(
        color_palette=palette,
        section_effects=section_effects,
        text_style='typewriter',
        intensity_curve='dynamic',
        bpm=audio_analysis.get('bpm', 120.0),
        sections=sections
    )


def _avg_energy_in_range(energy_envelope: list, start_ms: float, end_ms: float) -> float:
    """Calculate average energy in a time range."""
    vals = [e['energy'] for e in energy_envelope 
            if start_ms <= e['time_ms'] <= end_ms]
    return sum(vals) / len(vals) if vals else 0.5
