"""Stage 2: Lyrics retrieval from LRCLIB API."""
import re
import logging
import requests
from typing import List, Optional
from models.laser_types import SyncedLine, SyncedWord

logger = logging.getLogger(__name__)

LRCLIB_SEARCH = "https://lrclib.net/api/search"


def fetch_lyrics(title: str, artist: str, duration_s: float) -> List[SyncedLine]:
    """Fetch synced lyrics from LRCLIB API.
    
    Returns list of SyncedLine with word-level timings.
    Falls back to synthetic lyrics if none found.
    """
    try:
        params = {
            'track_name': title,
            'artist_name': artist,
        }
        logger.info(f"Searching LRCLIB for: '{title}' by '{artist}'")
        resp = requests.get(LRCLIB_SEARCH, params=params, timeout=10,
                           headers={'User-Agent': 'BabylonLaserShow/1.0'})
        
        if resp.status_code == 200:
            results = resp.json()
            if results:
                # Find best match with synced lyrics
                for result in results:
                    synced = result.get('syncedLyrics')
                    if synced:
                        logger.info(f"Found synced lyrics: {result.get('trackName')}")
                        lines = parse_lrc(synced, duration_s)
                        if lines:
                            return lines
                
                # Try plain lyrics
                for result in results:
                    plain = result.get('plainLyrics')
                    if plain:
                        logger.info("Found plain lyrics, creating synthetic timing")
                        return create_synthetic_lyrics(plain, duration_s)
        
        logger.info("No lyrics found on LRCLIB")
    except Exception as e:
        logger.warning(f"LRCLIB error: {e}")
    
    # Fallback: synthetic lyrics
    return create_fallback_lyrics(title, artist, duration_s)


def parse_lrc(lrc_text: str, duration_s: float) -> List[SyncedLine]:
    """Parse LRC format [MM:SS.CS]text into SyncedLine objects."""
    pattern = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)') 
    raw_lines = []
    
    for line in lrc_text.strip().split('\n'):
        m = pattern.match(line.strip())
        if m:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            centiseconds = m.group(3)
            # Handle both 2-digit (centiseconds) and 3-digit (milliseconds)
            if len(centiseconds) == 2:
                ms = int(centiseconds) * 10
            else:
                ms = int(centiseconds)
            
            timestamp_ms = (minutes * 60 + seconds) * 1000 + ms
            text = m.group(4).strip()
            if text:  # Skip empty lines
                raw_lines.append((timestamp_ms, text))
    
    if not raw_lines:
        return []
    
    # Build SyncedLine objects with end times
    lines = []
    duration_ms = duration_s * 1000
    
    for i, (start_ms, text) in enumerate(raw_lines):
        if i + 1 < len(raw_lines):
            end_ms = raw_lines[i + 1][0]
        else:
            end_ms = min(start_ms + 5000, duration_ms)  # Last line: 5s or end of song
        
        # Create word-level timings
        words = estimate_word_timings(text, start_ms, end_ms)
        lines.append(SyncedLine(text=text, start_ms=start_ms, end_ms=end_ms, words=words))
    
    return lines


def estimate_word_timings(text: str, start_ms: float, end_ms: float) -> List[SyncedWord]:
    """Estimate word timings proportional to character length.
    
    Minimum weight of 3 ensures short words get visible screen time.
    """
    raw_words = text.split()
    if not raw_words:
        return []
    
    line_duration = end_ms - start_ms
    if line_duration <= 0:
        line_duration = 2000  # Default 2s
    
    weights = [max(3, len(w)) for w in raw_words]
    total_weight = sum(weights)
    
    words = []
    cursor = start_ms
    
    for word_text, weight in zip(raw_words, weights):
        word_duration = line_duration * (weight / total_weight)
        words.append(SyncedWord(
            word=word_text,
            start_ms=cursor,
            end_ms=cursor + word_duration
        ))
        cursor += word_duration
    
    return words


def create_synthetic_lyrics(plain_text: str, duration_s: float) -> List[SyncedLine]:
    """Create evenly-spaced synthetic lyrics from plain text."""
    text_lines = [ln.strip() for ln in plain_text.strip().split('\n') if ln.strip()]
    if not text_lines:
        return []
    
    total_duration_ms = duration_s * 1000
    # Leave 5% gap at start and end
    start_offset = total_duration_ms * 0.05
    usable_duration = total_duration_ms * 0.9
    line_duration = usable_duration / len(text_lines)
    
    lines = []
    for i, text in enumerate(text_lines):
        start_ms = start_offset + i * line_duration
        end_ms = start_ms + line_duration * 0.9  # 90% display, 10% gap
        words = estimate_word_timings(text, start_ms, end_ms)
        lines.append(SyncedLine(text=text, start_ms=start_ms, end_ms=end_ms, words=words))
    
    return lines


def create_fallback_lyrics(title: str, artist: str, duration_s: float) -> List[SyncedLine]:
    """Create minimal fallback lyrics showing song info."""
    duration_ms = duration_s * 1000
    lines = []
    
    # Show title at start
    lines.append(SyncedLine(
        text=title.upper(),
        start_ms=1000,
        end_ms=5000,
        words=estimate_word_timings(title.upper(), 1000, 5000)
    ))
    
    # Show artist
    lines.append(SyncedLine(
        text=artist.upper(),
        start_ms=5500,
        end_ms=9000,
        words=estimate_word_timings(artist.upper(), 5500, 9000)
    ))
    
    return lines
