"""Stage 1: YouTube audio extraction using yt-dlp."""
import os
import re
import logging
from pathlib import Path
import yt_dlp

logger = logging.getLogger(__name__)

# Junk patterns to strip from titles
_JUNK_PATTERNS = [
    r'\s*\((?:Official\s+)?(?:Lyric[s]?\s+)?(?:Music\s+)?Video\)',
    r'\s*\[(?:Official\s+)?(?:Lyric[s]?\s+)?(?:Music\s+)?Video\]',
    r'\s*\(Official\s+Audio\)',
    r'\s*\(Audio\)',
    r'\s*\(Visuali[sz]er\)',
    r'\s*\[Official\]',
    r'\s*\(Official\)',
    r'\s*\|\s*Official\s+.*$',
    r'\s*HD$',
    r'\s*HQ$',
    r'\s*\(HQ\)',
    r'\s*\(HD\)',
    r'\s*ft\.?\s+.*$',    # strip "ft. someone" — LRCLIB matches better without it
    r'\s*feat\.?\s+.*$',
]


def _clean_title(raw: str) -> str:
    """Strip common YouTube junk from a title string."""
    cleaned = raw
    for pattern in _JUNK_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_audio(youtube_url: str, job_dir: Path) -> dict:
    """Download YouTube video and extract audio as WAV.

    Returns dict with: title, artist, duration, thumbnail_url, wav_path
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    wav_path = job_dir / "audio.wav"

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(job_dir / 'audio.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    logger.info(f"Downloading audio from: {youtube_url}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)

    # yt-dlp fields (in order of reliability):
    #   artist  — from metadata (reliable on official uploads, null on fan channels)
    #   track   — clean song name from metadata (often better than title)
    #   title   — full YouTube video title (often "Artist - Song (Official Video)")
    #   uploader/channel — the YouTube channel name (NOT the artist for fan uploads)
    raw_title = info.get('title', 'Unknown Title')
    meta_artist = info.get('artist') or ''
    meta_track = info.get('track') or ''
    uploader = info.get('uploader') or info.get('channel', '')
    duration = info.get('duration', 0)
    thumbnail = info.get('thumbnail', '')

    # Clean uploader
    if uploader.endswith(' - Topic'):
        uploader = uploader[:-8]

    # Strategy: figure out artist + title from best available source
    artist = ''
    title = ''

    if meta_artist and meta_track:
        # Best case: yt-dlp extracted both from metadata
        artist = meta_artist
        title = meta_track
        logger.info(f"Using metadata: artist={artist!r}, track={title!r}")
    elif ' - ' in raw_title:
        # Title has "Artist - Song" format — split it
        parts = raw_title.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        logger.info(f"Parsed from title: artist={artist!r}, title={title!r}")
    elif meta_artist:
        artist = meta_artist
        title = raw_title
    elif meta_track:
        title = meta_track
        artist = uploader  # best guess
    else:
        title = raw_title
        artist = uploader  # last resort

    # Clean junk from title
    title = _clean_title(title)
    artist = artist.strip()

    # If artist ended up empty, use uploader
    if not artist:
        artist = uploader or 'Unknown Artist'

    logger.info(f"Final: '{title}' by '{artist}' ({duration}s)")

    if not wav_path.exists():
        for f in job_dir.glob('audio.*'):
            if f.suffix == '.wav':
                wav_path = f
                break

    if not wav_path.exists():
        raise FileNotFoundError(f"WAV file not found at {wav_path}")

    return {
        'title': title,
        'artist': artist,
        'duration': duration,
        'thumbnail_url': thumbnail,
        'wav_path': str(wav_path),
    }
