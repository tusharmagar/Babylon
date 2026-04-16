"""Stage 3: Audio analysis using librosa."""
import logging
import numpy as np
import librosa

logger = logging.getLogger(__name__)


def analyze_audio(wav_path: str) -> dict:
    """Analyze WAV file for BPM, beats, energy, and segments.
    
    Returns:
        dict with: bpm, beat_times_ms, energy_envelope, 
                   segment_boundaries_ms, duration_ms, duration_s
    """
    logger.info(f"Analyzing audio: {wav_path}")
    
    # Load audio
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    duration_s = librosa.get_duration(y=y, sr=sr)
    duration_ms = duration_s * 1000
    
    logger.info(f"Audio loaded: {duration_s:.1f}s, sr={sr}")
    
    # BPM and beat times
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    beat_times_ms = [float(t * 1000) for t in beat_times]
    
    logger.info(f"BPM: {bpm:.1f}, {len(beat_times_ms)} beats detected")
    
    # RMS energy envelope downsampled to ~10 Hz
    hop_length = int(sr / 10)  # ~10 frames per second
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    
    # Normalize to 0-1
    rms_max = rms.max() if rms.max() > 0 else 1.0
    rms_normalized = rms / rms_max
    
    energy_envelope = []
    for i, energy in enumerate(rms_normalized):
        time_ms = float(i * hop_length / sr * 1000)
        energy_envelope.append({
            'time_ms': time_ms,
            'energy': float(energy)
        })
    
    logger.info(f"Energy envelope: {len(energy_envelope)} samples")
    
    # Segment boundaries from MFCC clustering
    try:
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        # Use agglomerative clustering for segment boundaries
        bound_frames = librosa.segment.agglomerative(mfccs, k=8)
        bound_times = librosa.frames_to_time(bound_frames, sr=sr)
        segment_boundaries_ms = sorted(set([0.0] + [float(t * 1000) for t in bound_times] + [duration_ms]))
    except Exception as e:
        logger.warning(f"Segmentation failed, using even splits: {e}")
        segment_boundaries_ms = [duration_ms * i / 8 for i in range(9)]
    
    logger.info(f"Segments: {len(segment_boundaries_ms) - 1} boundaries")
    
    return {
        'bpm': bpm,
        'beat_times_ms': beat_times_ms,
        'energy_envelope': energy_envelope,
        'segment_boundaries_ms': segment_boundaries_ms,
        'duration_ms': duration_ms,
        'duration_s': duration_s,
    }
