"""Stage 1: YouTube audio extraction using yt-dlp."""
import os
import json
import logging
from pathlib import Path
import yt_dlp

logger = logging.getLogger(__name__)


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
    
    # Extract metadata
    title = info.get('title', 'Unknown Title')
    artist = info.get('artist') or info.get('uploader') or info.get('channel', 'Unknown Artist')
    duration = info.get('duration', 0)
    thumbnail = info.get('thumbnail', '')
    
    # Clean artist name - remove " - Topic" suffix from YouTube auto-generated channels
    if artist.endswith(' - Topic'):
        artist = artist[:-8]
    
    # Try to parse title for artist - title format
    if ' - ' in title and artist in ('Unknown Artist', ''):
        parts = title.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
    logger.info(f"Extracted: '{title}' by '{artist}' ({duration}s)")
    
    if not wav_path.exists():
        # yt-dlp might have named it differently
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
