"""Lyrics retrieval from LRCLIB with word-timing estimation.
Matches the working babylon-laser implementation."""

import re
import logging
import httpx
from typing import List, Optional
from models.laser_types import SyncedLine, SyncedWord

logger = logging.getLogger(__name__)


async def fetch_lyrics(title: str, artist: str, duration_s: float) -> List[SyncedLine]:
    """Fetch synced lyrics from LRCLIB API.

    Uses /api/get with duration (accurate match), falls back to /api/search.
    Returns list of SyncedLine with word-level timings.
    Falls back to synthetic lyrics if none found.
    """
    try:
        # Primary: /api/get with duration (this is how LRCLIB matches accurately)
        params = {
            "artist_name": artist,
            "track_name": title,
            "duration": int(duration_s),
        }
        logger.info(f"Fetching lyrics from LRCLIB: '{title}' by '{artist}' ({int(duration_s)}s)")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://lrclib.net/api/get",
                params=params,
                timeout=10.0,
            )

            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics")
                if synced:
                    logger.info("Found synced lyrics via /api/get")
                    lines = parse_lrc(synced, duration_s)
                    if lines:
                        return lines

                # Try plain lyrics from same result
                plain = data.get("plainLyrics")
                if plain:
                    logger.info("Found plain lyrics via /api/get, creating synthetic timing")
                    return create_synthetic_lyrics(plain, duration_s)

            # Fallback: /api/search
            logger.info("Trying /api/search fallback...")
            resp = await client.get(
                "https://lrclib.net/api/search",
                params={"q": f"{artist} {title}"},
                timeout=10.0,
            )

            if resp.status_code == 200:
                results = resp.json()
                if results:
                    # Find first result with synced lyrics
                    for result in results:
                        synced = result.get("syncedLyrics")
                        if synced:
                            logger.info(f"Found synced lyrics via search: {result.get('trackName')}")
                            lines = parse_lrc(synced, duration_s)
                            if lines:
                                return lines

                    # Try plain lyrics
                    for result in results:
                        plain = result.get("plainLyrics")
                        if plain:
                            logger.info("Found plain lyrics via search")
                            return create_synthetic_lyrics(plain, duration_s)

        logger.info("No lyrics found on LRCLIB")
    except Exception as e:
        logger.warning(f"LRCLIB error: {e}")

    # Fallback: show title/artist
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
            if len(centiseconds) == 2:
                ms = int(centiseconds) * 10
            else:
                ms = int(centiseconds)

            timestamp_ms = (minutes * 60 + seconds) * 1000 + ms
            text = m.group(4).strip()
            if text:
                raw_lines.append((timestamp_ms, text))

    if not raw_lines:
        return []

    lines = []
    duration_ms = duration_s * 1000

    for i, (start_ms, text) in enumerate(raw_lines):
        if i + 1 < len(raw_lines):
            end_ms = raw_lines[i + 1][0]
        else:
            end_ms = duration_ms

        words = estimate_word_timings(text, start_ms, end_ms)
        lines.append(SyncedLine(text=text, start_ms=start_ms, end_ms=end_ms, words=words))

    return lines


def estimate_word_timings(text: str, start_ms: float, end_ms: float) -> List[SyncedWord]:
    """Estimate word timings proportional to character length."""
    raw_words = text.split()
    if not raw_words:
        return []

    line_duration = end_ms - start_ms
    if line_duration <= 0:
        line_duration = 2000

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
    start_offset = total_duration_ms * 0.05
    usable_duration = total_duration_ms * 0.9
    line_duration = usable_duration / len(text_lines)

    lines = []
    for i, text in enumerate(text_lines):
        start_ms = start_offset + i * line_duration
        end_ms = start_ms + line_duration * 0.9
        words = estimate_word_timings(text, start_ms, end_ms)
        lines.append(SyncedLine(text=text, start_ms=start_ms, end_ms=end_ms, words=words))

    return lines


def create_fallback_lyrics(title: str, artist: str, duration_s: float) -> List[SyncedLine]:
    """Create minimal fallback lyrics showing song info."""
    lines = []
    lines.append(SyncedLine(
        text=title.upper(),
        start_ms=1000,
        end_ms=5000,
        words=estimate_word_timings(title.upper(), 1000, 5000)
    ))
    lines.append(SyncedLine(
        text=artist.upper(),
        start_ms=5500,
        end_ms=9000,
        words=estimate_word_timings(artist.upper(), 5500, 9000)
    ))
    return lines
