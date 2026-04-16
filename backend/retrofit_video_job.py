"""One-off: retrofit an existing jobs/video_*/ directory with frames.pkl + meta.json
so it shows up in the Library after a backend restart.

Usage: python retrofit_video_job.py <job_id> [title] [duration_s]
"""
import sys
import json
import pickle
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from services.video_processor import vectorize_video


def retrofit(job_id: str, title: str = "", duration_s: int = 0):
    job_dir = ROOT / "jobs" / job_id
    if not job_dir.exists():
        print(f"ERROR: {job_dir} does not exist")
        return 1

    video_path = job_dir / "video.mp4"
    audio_path = job_dir / "audio.wav"
    frames_pkl = job_dir / "frames.pkl"
    meta_json = job_dir / "meta.json"

    if not video_path.exists() or not audio_path.exists():
        print(f"ERROR: missing video.mp4 or audio.wav in {job_dir}")
        return 1

    print(f"Vectorizing {video_path} ...")
    frames = vectorize_video(video_path, max_points=800)
    if not frames:
        print("ERROR: no frames produced")
        return 1

    print(f"Writing {frames_pkl} ({len(frames)} frames) ...")
    with open(frames_pkl, "wb") as f:
        pickle.dump(frames, f, protocol=pickle.HIGHEST_PROTOCOL)

    total_ms = frames[-1].timestamp_ms if frames else 0
    meta = {
        "job_id": job_id,
        "source": "video",
        "status": "complete",
        "job_dir": str(job_dir),
        "audio_path": str(audio_path),
        "video_path": str(video_path),
        "frames_path": str(frames_pkl),
        "total_frames": len(frames),
        "duration_ms": total_ms,
        "max_points": 800,
        "metadata": {
            "title": title or job_id,
            "artist": "",
            "duration": duration_s or int(total_ms / 1000),
            "thumbnail_url": "",
        },
    }
    meta_json.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {meta_json}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python retrofit_video_job.py <job_id> [title] [duration_s]")
        sys.exit(1)
    job_id = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    dur = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    sys.exit(retrofit(job_id, title, dur))
