from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import os
import json
import logging
import asyncio
import socket
import subprocess
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from ai_agent import BeyondAIAgent
from sdk_manager import BeyondSDKManager
import database as db

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy polling logs from uvicorn — only log non-GET or non-200 requests
class PollFilter(logging.Filter):
    """Filter out repetitive polling GET requests (status, logs, laser/status)."""
    POLL_PATHS = {"/api/status", "/api/logs", "/api/laser/status"}
    def filter(self, record):
        msg = record.getMessage()
        if "GET" in msg and "200" in msg:
            for path in self.POLL_PATHS:
                if path in msg:
                    return False
        return True

logging.getLogger("uvicorn.access").addFilter(PollFilter())


# ===== TCP Connection Manager for PangoScript (Cues) =====
class BeyondConnectionManager:
    """Manages TCP connection to BEYOND's PangoScript interface (port 16063).
    Used for controlling existing cues — StartCue, StopCue, StopAllNow, blackout commands.
    """
    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.host: Optional[str] = None
        self.port: Optional[int] = None
        self.connected: bool = False
        self.lock = asyncio.Lock()
        self.command_logs: List[dict] = []
        self.max_logs = 100
        self.echo_mode = 1

    def add_log(self, log_type: str, message: str, response: str = None):
        log_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": log_type,
            "message": message,
            "response": response
        }
        self.command_logs.append(log_entry)
        if len(self.command_logs) > self.max_logs:
            self.command_logs.pop(0)
        logger.info(f"[{log_type}] {message} -> {response}")
        return log_entry

    async def connect(self, host: str, port: int, timeout: float = 5.0) -> bool:
        async with self.lock:
            try:
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None
                    self.connected = False

                self.host = host
                self.port = port
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(timeout)
                # Run blocking connect in thread to avoid freezing the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.socket.connect, (host, port))
                self.connected = True
                self.add_log("CONNECTION", f"Connected to {host}:{port}")
                await self._send_raw_internal(f"SetEchoMode {self.echo_mode}")
                return True

            except socket.timeout:
                self.add_log("ERROR", f"Connection timeout to {host}:{port}")
                self.connected = False
                return False
            except ConnectionRefusedError:
                self.add_log("ERROR", f"Connection refused by {host}:{port}")
                self.connected = False
                return False
            except Exception as e:
                self.add_log("ERROR", f"Connection error: {str(e)}")
                self.connected = False
                return False

    async def disconnect(self):
        async with self.lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            self.connected = False
            self.add_log("CONNECTION", "Disconnected")

    def _send_sync(self, command: str) -> str:
        """Blocking send — runs in executor thread so it doesn't freeze the event loop."""
        full_command = f"{command}\r\n"
        self.socket.sendall(full_command.encode('ascii'))
        self.socket.settimeout(1.5)
        try:
            response = self.socket.recv(1024).decode('ascii', errors='replace').strip()
        except socket.timeout:
            response = "(no response)"
        return response

    async def _send_raw_internal(self, command: str) -> Optional[str]:
        if not self.socket or not self.connected:
            return None
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self._send_sync, command),
                timeout=2.5,
            )
            return response
        except (asyncio.TimeoutError, Exception) as e:
            self.connected = False
            raise e

    async def send_command(self, command: str) -> dict:
        async with self.lock:
            if not self.socket or not self.connected:
                log = self.add_log("ERROR", command, "Not connected to BEYOND")
                return {"success": False, "error": "Not connected", "log": log}
            try:
                response = await self._send_raw_internal(command)
                log = self.add_log("COMMAND", command, response)
                return {"success": True, "response": response, "log": log}
            except Exception as e:
                self.connected = False
                log = self.add_log("ERROR", command, str(e))
                return {"success": False, "error": str(e), "log": log}

    def get_status(self) -> dict:
        return {
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "echo_mode": self.echo_mode
        }

    def get_logs(self, limit: int = 50) -> List[dict]:
        return self.command_logs[-limit:]


# ===== Global Instances =====
beyond_manager = BeyondConnectionManager()
sdk_manager = BeyondSDKManager()

# Let sdk_manager use the live TCP socket for StopAllNow (works with remote/ngrok BEYOND)
import sdk_manager as _sdk_manager_module
_sdk_manager_module.set_beyond_manager(beyond_manager)

ai_agent = None
try:
    ai_agent = BeyondAIAgent()
    logger.info("AI Agent initialized")
except Exception as e:
    logger.warning(f"AI Agent not available: {e}")


# ===== Pydantic Models =====
class ConnectionConfigCreate(BaseModel):
    host: str
    port: int
    timeout: float = 5.0

class CommandRequest(BaseModel):
    command: str

class CueRequest(BaseModel):
    page: int = 1
    cue: int

class CommandResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    log: Optional[dict] = None

class ChatMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class LaserSendRequest(BaseModel):
    point_data: List[Dict[str, Any]]
    pattern_name: str = ""

class YouTubeAnalyzeRequest(BaseModel):
    youtube_url: str


# ===== Lifespan =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()
    sdk_manager.initialize()
    sdk_manager.start_send_loop()
    _load_library_from_disk()
    logger.info("Server started — DB initialized, SDK manager running")
    yield
    # Shutdown
    await beyond_manager.disconnect()
    sdk_manager.shutdown()
    logger.info("Server shut down cleanly")


def _load_library_from_disk():
    """Scan jobs/ directory and rebuild _active_jobs from meta.json files."""
    jobs_dir = ROOT_DIR / "jobs"
    if not jobs_dir.exists():
        return
    count = 0
    for meta_file in jobs_dir.glob("*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text())
            job_id = meta.get("job_id") or meta_file.parent.name
            meta["job_id"] = job_id
            _active_jobs[job_id] = meta
            count += 1
        except Exception as e:
            logger.warning(f"Failed to load {meta_file}: {e}")
    logger.info(f"Library: loaded {count} saved songs from disk")


# Create app
app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "BEYOND Control API — SDK + PangoScript"}


@api_router.get("/health")
async def health():
    """Debug endpoint — check what's working."""
    return {
        "ai_agent": ai_agent is not None,
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "openai_key_prefix": (os.environ.get("OPENAI_API_KEY") or "")[:12] + "...",
        "sdk_initialized": sdk_manager.initialized,
        "sdk_simulation": sdk_manager.simulation_mode,
    }


@api_router.get("/test-circle")
async def test_circle():
    """Send a green circle directly using the SDK — bypasses background thread."""
    import ctypes, math
    from sdk_manager import SdkPoint

    if not sdk_manager._dll or not sdk_manager._ready:
        return {"error": "SDK not ready"}

    NUM = 64
    RADIUS = 15000.0
    GREEN = 0 | (255 << 8) | (0 << 16)

    arr = (SdkPoint * NUM)()
    for i in range(NUM):
        angle = 2 * math.pi * i / NUM
        arr[i].x = RADIUS * math.cos(angle)
        arr[i].y = RADIUS * math.sin(angle)
        arr[i].z = 0.0
        arr[i].color = GREEN
        arr[i].rep_count = 0
        arr[i].focus = 0
        arr[i].status = 0
        arr[i].zero = 0

    # Send 150 frames (~5 seconds) directly from this thread
    results = []
    import time
    for f in range(150):
        r = sdk_manager._dll.ldbSendFrameToImage(
            sdk_manager._image_name, NUM,
            ctypes.byref(arr), ctypes.byref(sdk_manager._zone_arr),
            -30000,
        )
        if f < 5:
            results.append(r)
        time.sleep(1/30)

    return {
        "frames_sent": 150,
        "first_5_results": results,
        "image_name": sdk_manager._image_name.decode(),
        "point0": f"({arr[0].x:.0f},{arr[0].y:.0f},c={arr[0].color})",
    }


# ===== PangoScript TCP Endpoints (Cues Page) =====

@api_router.get("/config")
async def get_config():
    """Get the saved PangoScript connection configuration."""
    config = db.get_pangoscript_config()
    if config:
        return config
    return {"host": "", "port": 16063, "timeout": 5.0}


@api_router.post("/config")
async def save_config(config: ConnectionConfigCreate):
    """Save PangoScript connection configuration."""
    saved = db.save_pangoscript_config(config.host, config.port, config.timeout)
    return {"success": True, "config": saved}


@api_router.post("/connect")
async def connect_beyond(config: ConnectionConfigCreate):
    """Connect to BEYOND via PangoScript TCP (through ngrok endpoint)."""
    db.save_pangoscript_config(config.host, config.port, config.timeout)
    success = await beyond_manager.connect(config.host, config.port, config.timeout)
    if success:
        return {"success": True, "message": f"Connected to {config.host}:{config.port}"}
    else:
        raise HTTPException(status_code=503, detail=f"Failed to connect to {config.host}:{config.port}")


@api_router.post("/disconnect")
async def disconnect_beyond():
    """Disconnect from BEYOND PangoScript."""
    await beyond_manager.disconnect()
    return {"success": True, "message": "Disconnected"}


@api_router.get("/status")
async def get_status():
    """Get PangoScript connection status."""
    return beyond_manager.get_status()


@api_router.post("/test-connection")
async def test_connection():
    """Test the PangoScript connection."""
    if not beyond_manager.connected:
        return {"success": False, "error": "Not connected"}
    result = await beyond_manager.send_command("Hello")
    return result


@api_router.post("/command", response_model=CommandResponse)
async def send_command(request: CommandRequest):
    """Send a raw PangoScript command."""
    result = await beyond_manager.send_command(request.command)
    return CommandResponse(**result)


@api_router.post("/cue/start", response_model=CommandResponse)
async def start_cue(request: CueRequest):
    """Start a specific cue (1-indexed)."""
    command = f"StartCue {request.page},{request.cue}"
    result = await beyond_manager.send_command(command)
    return CommandResponse(**result)


@api_router.post("/cue/stop", response_model=CommandResponse)
async def stop_cue(request: CueRequest):
    """Stop a specific cue."""
    command = f"StopCue {request.page},{request.cue}"
    result = await beyond_manager.send_command(command)
    return CommandResponse(**result)


@api_router.post("/stop-all", response_model=CommandResponse)
async def stop_all():
    """Stop all playback immediately."""
    result = await beyond_manager.send_command("StopAllNow")
    return CommandResponse(**result)


@api_router.post("/blackout/on", response_model=CommandResponse)
async def blackout_on():
    """Enable blackout (disable laser output)."""
    result = await beyond_manager.send_command("DisableLaserOutput")
    return CommandResponse(**result)


@api_router.post("/blackout/off", response_model=CommandResponse)
async def blackout_off():
    """Disable blackout (enable laser output)."""
    result = await beyond_manager.send_command("EnableLaserOutput")
    return CommandResponse(**result)


@api_router.post("/blackout/toggle", response_model=CommandResponse)
async def blackout_toggle():
    """Toggle blackout state."""
    result = await beyond_manager.send_command("ToggleBlackout")
    return CommandResponse(**result)


@api_router.get("/logs")
async def get_logs(limit: int = 50):
    """Get recent PangoScript command logs."""
    return {"logs": beyond_manager.get_logs(limit)}


@api_router.delete("/logs")
async def clear_logs():
    """Clear command logs."""
    beyond_manager.command_logs = []
    return {"success": True, "message": "Logs cleared"}


# ===== SDK / Laser Endpoints (AI Builder) =====

@api_router.get("/laser/status")
async def laser_status():
    """Get current SDK and streaming status."""
    return sdk_manager.get_status()


@api_router.post("/laser/send")
async def laser_send(request: LaserSendRequest):
    """Send point data to the laser. Instantly replaces current pattern."""
    if not sdk_manager.initialized:
        raise HTTPException(status_code=503, detail="SDK not initialized")

    logger.info(f"LASER SEND: {len(request.point_data)} points, pattern={request.pattern_name!r}")
    if request.point_data:
        sample = request.point_data[:3]
        logger.info(f"LASER SEND: First 3 points: {sample}")

    await sdk_manager.set_points(request.point_data, request.pattern_name)
    return {
        "success": True,
        "point_count": len(request.point_data),
        "pattern_name": request.pattern_name,
        "simulation_mode": sdk_manager.simulation_mode,
    }


@api_router.post("/laser/blackout")
async def laser_blackout():
    """Clear the laser — stop all output."""
    sdk_manager.blackout()
    return {"success": True, "message": "Blackout — laser cleared"}


@api_router.post("/laser/stop")
async def laser_stop():
    """Stop streaming (clear points, keep loop running)."""
    await sdk_manager.set_points([], "")
    return {"success": True, "message": "Streaming stopped"}


# ===== Chat / AI Endpoints =====

@api_router.post("/chat/new")
async def create_chat_session():
    """Create a new chat session."""
    session = db.create_session()
    return session


@api_router.get("/chat/sessions")
async def list_chat_sessions():
    """List all chat sessions."""
    sessions = db.list_sessions()
    return {"sessions": sessions}


@api_router.get("/chat/{session_id}/messages")
async def get_chat_messages(session_id: str):
    """Get all messages for a chat session."""
    messages = db.get_messages(session_id)
    return {"messages": messages}


@api_router.delete("/chat/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete a chat session and its messages."""
    db.delete_session(session_id)
    return {"success": True}


@api_router.post("/chat/send")
async def send_chat_message(request: ChatMessageRequest):
    """Send a message to the AI agent and get a laser pattern response."""
    logger.info(f"CHAT: Received message: {request.message[:80]!r}")

    if not ai_agent:
        logger.error("CHAT: AI Agent is None — OPENAI_API_KEY missing or init failed")
        raise HTTPException(status_code=503, detail="AI Agent not available. Check OPENAI_API_KEY.")

    session_id = request.session_id

    # Create session if needed
    if not session_id:
        session = db.create_session(title=request.message[:50])
        session_id = session["id"]
    else:
        # Update session
        existing = db.get_session(session_id)
        if existing:
            title_update = request.message[:50] if existing.get("title") == "New Chat" else None
            db.update_session(session_id, title=title_update)

    # Save user message
    db.add_message(session_id=session_id, role="user", content=request.message)

    # Build conversation history for context
    history = db.get_recent_history(session_id, limit=10)

    # Generate AI response
    logger.info("CHAT: Calling OpenAI...")
    ai_response = await ai_agent.generate_pattern(
        user_message=request.message,
        session_id=session_id,
        history=history[:-1]  # Exclude the message we just added
    )
    logger.info(f"CHAT: Got response — pattern={ai_response.get('pattern_name')!r}, points={len(ai_response.get('point_data', []))}")

    # Save AI response
    msg_id = db.add_message(
        session_id=session_id,
        role="assistant",
        content=ai_response.get("message", ""),
        ai_message=ai_response.get("message", ""),
        pattern_name=ai_response.get("pattern_name", ""),
        point_data=ai_response.get("point_data", []),
        python_code=ai_response.get("python_code", ""),
    )

    return {
        "session_id": session_id,
        "message": ai_response.get("message", ""),
        "pattern_name": ai_response.get("pattern_name", ""),
        "point_data": ai_response.get("point_data", []),
        "python_code": ai_response.get("python_code", ""),
        "message_id": msg_id,
    }


# ===== YouTube-to-Laser Pipeline =====

# Job storage for tracking active pipeline jobs
_active_jobs: Dict[str, dict] = {}
_stored_frames: Dict[str, list] = {}  # job_id -> list of LaserFrame (for SDK streaming)
JOBS_DIR = ROOT_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

@api_router.post("/youtube/analyze")
async def youtube_analyze(request: YouTubeAnalyzeRequest):
    """Run the full YouTube-to-Laser pipeline with SSE progress streaming."""
    
    async def event_generator():
        job_id = str(uuid.uuid4())[:8]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        
        _active_jobs[job_id] = {"status": "starting", "job_dir": str(job_dir)}
        
        def send_event(stage: str, data: dict = None):
            payload = {"stage": stage, "job_id": job_id}
            if data:
                payload.update(data)
            return json.dumps(payload)
        
        try:
            # Stage 1: Extract audio
            yield {"event": "progress", "data": send_event("extracting_audio")}
            
            from services.youtube import extract_audio
            metadata = await asyncio.get_event_loop().run_in_executor(
                None, extract_audio, request.youtube_url, job_dir
            )
            
            yield {"event": "progress", "data": send_event("extracting_audio_done", {
                "title": metadata['title'],
                "artist": metadata['artist'],
                "duration": metadata['duration'],
                "thumbnail_url": metadata.get('thumbnail_url', ''),
            })}
            
            # Stage 2: Fetch lyrics
            yield {"event": "progress", "data": send_event("fetching_lyrics")}
            
            from services.lyrics import fetch_lyrics
            lyrics = await fetch_lyrics(metadata['title'], metadata['artist'], metadata['duration'])
            
            yield {"event": "progress", "data": send_event("fetching_lyrics_done", {
                "lyric_count": len(lyrics),
                "has_synced": any(l.words for l in lyrics),
            })}
            
            # Stage 3: Analyze audio
            yield {"event": "progress", "data": send_event("analyzing_audio")}
            
            from services.audio_analysis import analyze_audio
            analysis = await asyncio.get_event_loop().run_in_executor(
                None, analyze_audio, metadata['wav_path']
            )
            
            yield {"event": "progress", "data": send_event("analyzing_audio_done", {
                "bpm": analysis['bpm'],
                "beat_count": len(analysis['beat_times_ms']),
                "segments": len(analysis['segment_boundaries_ms']) - 1,
            })}
            
            # Stage 4: Design show
            yield {"event": "progress", "data": send_event("designing_show")}
            
            from services.song_interpreter import design_show
            design = await design_show(lyrics, analysis, metadata['title'], metadata['artist'])
            
            yield {"event": "progress", "data": send_event("designing_show_done", {
                "sections": len(design.sections),
                "text_style": design.text_style,
                "palette_size": len(design.color_palette),
            })}
            
            # Stage 5: Generate frames
            yield {"event": "progress", "data": send_event("generating_frames")}
            
            from services.laser_generator import generate_show
            from services.point_optimizer import optimize_frame

            def generate_and_optimize(lyrics, design, analysis):
                frames = generate_show(lyrics, design, analysis)
                for frame in frames:
                    frame.points = optimize_frame(frame.points)
                return frames

            frames = await asyncio.get_event_loop().run_in_executor(
                None, generate_and_optimize, lyrics, design, analysis
            )
            
            # Store frames in memory for SDK streaming
            _stored_frames[job_id] = frames

            yield {"event": "progress", "data": send_event("generating_frames_done", {
                "total_frames": len(frames),
                "duration_s": analysis['duration_s'],
            })}

            # Stage 6: Write ILDA file
            yield {"event": "progress", "data": send_event("writing_ilda")}
            
            from services.ilda_writer import write_ilda_file
            # Sanitize filename: only keep letters, digits, spaces, hyphens, underscores
            import re as _re
            raw_name = f"{metadata['artist']}_{metadata['title']}"
            safe_name = _re.sub(r'[^\w\s-]', '', raw_name)
            safe_name = _re.sub(r'\s+', '_', safe_name).strip('_')
            ilda_filename = (safe_name[:60] or "show") + ".ild"
            ilda_path = job_dir / ilda_filename
            
            file_size = await asyncio.get_event_loop().run_in_executor(
                None, write_ilda_file, frames, ilda_path
            )
            
            yield {"event": "progress", "data": send_event("writing_ilda_done", {
                "ilda_filename": ilda_filename,
                "file_size_kb": round(file_size / 1024, 1),
            })}
            
            # Store job info for download
            _active_jobs[job_id] = {
                "status": "complete",
                "job_id": job_id,
                "job_dir": str(job_dir),
                "ilda_path": str(ilda_path),
                "ilda_filename": ilda_filename,
                "metadata": {
                    "title": metadata['title'],
                    "artist": metadata['artist'],
                    "duration": metadata['duration'],
                    "thumbnail_url": metadata.get('thumbnail_url', ''),
                },
                "bpm": analysis['bpm'],
                "total_frames": len(frames),
                "file_size_kb": round(file_size / 1024, 1),
                "sections": [{"label": s.label, "start_ms": s.start_ms, "end_ms": s.end_ms, "energy": s.energy} for s in design.sections],
                "lyric_count": len(lyrics),
                "design": {
                    "text_style": design.text_style,
                    "intensity_curve": design.intensity_curve,
                    "palette": [list(c) for c in design.color_palette],
                },
            }
            
            # Save metadata to disk so we can rebuild library on restart
            meta_path = job_dir / "meta.json"
            meta_path.write_text(json.dumps(_active_jobs[job_id], indent=2))

            # Complete event
            yield {"event": "complete", "data": json.dumps(_active_jobs[job_id])}
            
        except Exception as e:
            logger.error(f"YouTube pipeline error: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({
                "stage": "error",
                "job_id": job_id,
                "error": str(e),
            })}
    
    return EventSourceResponse(event_generator())


@api_router.get("/youtube/download/{job_id}")
async def youtube_download(job_id: str):
    """Download the generated .ild file for a job."""
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    ilda_path = job.get('ilda_path')
    if not ilda_path or not Path(ilda_path).exists():
        raise HTTPException(status_code=404, detail="ILDA file not found")
    
    return FileResponse(
        path=ilda_path,
        filename=job.get('ilda_filename', 'show.ild'),
        media_type='application/octet-stream',
    )


@api_router.get("/youtube/job/{job_id}")
async def youtube_job_status(job_id: str):
    """Get the status of a YouTube pipeline job."""
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ===== GIF Library Endpoints =====

GIFS_DIR = ROOT_DIR / "gifs"
GIFS_DIR.mkdir(exist_ok=True)


class GifUploadRequest(BaseModel):
    url: str
    name: Optional[str] = None


def _load_gif_library():
    """Scan gifs/ and return list of all saved GIFs."""
    items = []
    for meta_file in GIFS_DIR.glob("*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text())
            items.append(meta)
        except Exception as e:
            logger.warning(f"Failed to load {meta_file}: {e}")
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items


@api_router.post("/gifs/upload")
async def gifs_upload(request: GifUploadRequest):
    """Download + vectorize a GIF from a URL and save to the library."""
    from services.gif_processor import download_gif, vectorize_gif

    gif_id = str(uuid.uuid4())[:8]
    gif_dir = GIFS_DIR / gif_id
    gif_dir.mkdir()

    try:
        # Download (blocking I/O — use executor)
        loop = asyncio.get_event_loop()
        gif_bytes = await loop.run_in_executor(None, download_gif, request.url)

        source_path = gif_dir / "source.gif"
        source_path.write_bytes(gif_bytes)

        # Vectorize (CPU-bound — use executor)
        frames, durations, size = await loop.run_in_executor(
            None, vectorize_gif, gif_bytes
        )

        if not frames:
            raise ValueError("No frames could be vectorized")

        # Save frames as compact JSON (nested lists)
        frames_path = gif_dir / "frames.json"
        frames_path.write_text(json.dumps({
            "frames": [[list(p) for p in f] for f in frames],
            "durations_ms": durations,
        }))

        # Derive name
        name = request.name or request.url.split("/")[-1].split("?")[0] or gif_id
        if len(name) > 50:
            name = name[:50]

        avg_pts = sum(len(f) for f in frames) / len(frames)
        total_ms = sum(durations)

        meta = {
            "gif_id": gif_id,
            "name": name,
            "source_url": request.url,
            "frame_count": len(frames),
            "duration_ms": total_ms,
            "avg_points": round(avg_pts),
            "width": size[0],
            "height": size[1],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (gif_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        return meta

    except Exception as e:
        # Cleanup on failure
        import shutil
        if gif_dir.exists():
            shutil.rmtree(gif_dir)
        logger.error(f"GIF upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/gifs")
async def gifs_list():
    """List all saved GIFs."""
    return {"gifs": _load_gif_library()}


@api_router.get("/gifs/{gif_id}/preview")
async def gifs_preview(gif_id: str):
    """Serve the original GIF file."""
    source = GIFS_DIR / gif_id / "source.gif"
    if not source.exists():
        raise HTTPException(status_code=404, detail="GIF not found")
    return FileResponse(path=source, media_type="image/gif")


@api_router.post("/gifs/{gif_id}/play")
async def gifs_play(gif_id: str):
    """Play a GIF on the laser (loops until stopped)."""
    frames_path = GIFS_DIR / gif_id / "frames.json"
    meta_path = GIFS_DIR / gif_id / "meta.json"
    if not frames_path.exists() or not meta_path.exists():
        raise HTTPException(status_code=404, detail="GIF not found")

    data = json.loads(frames_path.read_text())
    meta = json.loads(meta_path.read_text())

    # Convert back from JSON lists to tuples
    frames = [[tuple(p) for p in f] for f in data["frames"]]
    durations = data["durations_ms"]

    await sdk_manager.play_gif(frames, durations, gif_name=meta.get("name", gif_id))
    return {
        "status": "playing",
        "gif_id": gif_id,
        "frame_count": len(frames),
        "duration_ms": sum(durations),
    }


@api_router.post("/gifs/stop")
async def gifs_stop():
    """Stop GIF playback."""
    await sdk_manager.stop_gif()
    return {"status": "stopped"}


@api_router.delete("/gifs/{gif_id}")
async def gifs_delete(gif_id: str):
    """Delete a saved GIF."""
    import shutil
    gif_dir = GIFS_DIR / gif_id
    if not gif_dir.exists():
        raise HTTPException(status_code=404, detail="GIF not found")

    # Stop if currently playing this GIF
    if sdk_manager.current_gif_name and sdk_manager.gif_active:
        await sdk_manager.stop_gif()

    shutil.rmtree(gif_dir)
    return {"success": True}


# ===== Library Endpoints =====

@api_router.get("/library")
async def library_list():
    """List all saved songs (from meta.json files on disk)."""
    items = []
    for job_id, job in _active_jobs.items():
        if job.get("status") != "complete":
            continue
        meta = job.get("metadata", {})
        items.append({
            "job_id": job_id,
            "title": meta.get("title", "Unknown"),
            "artist": meta.get("artist", "Unknown"),
            "duration": meta.get("duration", 0),
            "thumbnail_url": meta.get("thumbnail_url", ""),
            "bpm": job.get("bpm", 0),
            "total_frames": job.get("total_frames", 0),
            "file_size_kb": job.get("file_size_kb", 0),
            "ilda_filename": job.get("ilda_filename", ""),
        })
    # Sort newest first (by job_id which is uuid, so just reverse insertion order)
    return {"songs": items}


@api_router.delete("/library/{job_id}")
async def library_delete(job_id: str):
    """Delete a saved song (removes job dir and .ild + audio)."""
    import shutil
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Song not found")

    job_dir = Path(job.get("job_dir", ""))
    if job_dir.exists() and job_dir.is_relative_to(ROOT_DIR / "jobs"):
        shutil.rmtree(job_dir)

    _active_jobs.pop(job_id, None)
    _stored_frames.pop(job_id, None)

    return {"success": True}


# ===== SDK Streaming Endpoints =====

class StreamRequest(BaseModel):
    job_id: str


@api_router.post("/stream/start")
async def stream_start(request: StreamRequest):
    """Start streaming frames to BEYOND SDK with audio playback.
    Routes through the shared sdk_manager so we don't double-load the DLL."""
    job = _active_jobs.get(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If frames are not in memory (server restarted), load them from disk
    frames = _stored_frames.get(request.job_id)
    if not frames:
        loop = asyncio.get_event_loop()
        # Video jobs persist as pickle; song jobs as .ild
        frames_pkl = Path(job.get('frames_path', ''))
        ilda_path = Path(job.get('ilda_path', ''))
        if frames_pkl.exists():
            import pickle
            logger.info(f"Loading frames from {frames_pkl}")
            def _load_pkl():
                with open(frames_pkl, "rb") as f:
                    return pickle.load(f)
            frames = await loop.run_in_executor(None, _load_pkl)
        elif ilda_path.exists():
            from services.ilda_reader import read_ilda_file
            logger.info(f"Loading frames from {ilda_path}")
            frames = await loop.run_in_executor(None, read_ilda_file, ilda_path)
        else:
            raise HTTPException(status_code=404, detail="No frames or .ild file found")
        _stored_frames[request.job_id] = frames

    audio_path = Path(job['job_dir']) / "audio.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    song_name = job.get("song_title") or job.get("title") or request.job_id
    ok = await sdk_manager.play_song(frames, audio_path, song_name=song_name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to start SDK song playback")

    return {
        "status": "streaming",
        "message": "BEYOND SDK playback started",
        "total_frames": len(frames),
        "total_duration_ms": sdk_manager.song_total_ms,
    }


@api_router.post("/stream/stop")
async def stream_stop():
    """Stop BEYOND SDK streaming."""
    await sdk_manager.stop_song()
    return {"status": "stopped"}


@api_router.get("/stream/status")
async def stream_status():
    """Get current SDK streaming status."""
    return {
        "playing": sdk_manager.song_active,
        "current_time_ms": (sdk_manager._song_audio_position / sdk_manager._song_audio_sr * 1000.0) if sdk_manager._song_audio_sr else 0,
        "total_duration_ms": sdk_manager.song_total_ms,
        "frames_sent": sdk_manager.song_frames_sent,
        "sdk": {"connected": sdk_manager._ready, "simulation": sdk_manager.simulation_mode},
        "error": sdk_manager.last_error,
    }


# ===== Video → Laser =====

class VideoStreamRequest(BaseModel):
    url: str
    duration_s: float = 45.0
    max_points: int = 800
    k_colors: int = 5


@api_router.post("/video/stream")
async def video_stream(request: VideoStreamRequest):
    """Download a YouTube video, vectorize the first N seconds with color,
    and play it on the laser synced to the original audio.

    Persists frames + audio to disk so the job shows up in the Library and
    can be replayed later without re-downloading or re-vectorizing."""
    from services.video_processor import download_video_with_audio, vectorize_video
    import pickle

    job_id = f"video_{uuid.uuid4().hex[:8]}"
    out_dir = JOBS_DIR / job_id

    loop = asyncio.get_event_loop()

    def _download_and_vectorize():
        video_path, audio_path, info = download_video_with_audio(
            request.url, out_dir, duration_s=request.duration_s
        )
        frames = vectorize_video(
            video_path, max_points=request.max_points, k_colors=request.k_colors
        )
        return frames, audio_path, video_path, info

    try:
        frames, audio_path, video_path, yt_info = await loop.run_in_executor(
            None, _download_and_vectorize
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {stderr[-400:]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video processing failed: {e}")

    if not frames:
        raise HTTPException(status_code=500, detail="No frames vectorized from video")

    # Persist the vectorized frames + metadata for future replay
    def _persist():
        frames_pkl = out_dir / "frames.pkl"
        with open(frames_pkl, "wb") as f:
            pickle.dump(frames, f, protocol=pickle.HIGHEST_PROTOCOL)
        meta = {
            "job_id": job_id,
            "source": "video",
            "source_url": request.url,
            "status": "complete",
            "job_dir": str(out_dir),
            "audio_path": str(audio_path),
            "video_path": str(video_path),
            "frames_path": str(frames_pkl),
            "total_frames": len(frames),
            "duration_ms": frames[-1].timestamp_ms if frames else 0,
            "max_points": request.max_points,
            "metadata": {
                "title": (yt_info or {}).get("title", job_id),
                "artist": (yt_info or {}).get("uploader", ""),
                "duration": int((yt_info or {}).get("duration") or ((frames[-1].timestamp_ms if frames else 0) / 1000)),
                "thumbnail_url": (yt_info or {}).get("thumbnail", ""),
            },
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        return meta

    meta = await loop.run_in_executor(None, _persist)
    _active_jobs[job_id] = meta
    _stored_frames[job_id] = frames

    ok = await sdk_manager.play_song(frames, audio_path, song_name=job_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to start SDK playback")

    return {
        "status": "streaming",
        "job_id": job_id,
        "frames": len(frames),
        "total_duration_ms": sdk_manager.song_total_ms,
        "video_path": str(video_path),
        "audio_path": str(audio_path),
    }


# ===== Wire Up =====
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
