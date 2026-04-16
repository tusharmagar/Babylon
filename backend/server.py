from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import asyncio
import socket
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
                self.socket.connect((host, port))
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

    async def _send_raw_internal(self, command: str) -> Optional[str]:
        if not self.socket or not self.connected:
            return None
        try:
            full_command = f"{command}\r\n"
            self.socket.sendall(full_command.encode('ascii'))
            self.socket.settimeout(2.0)
            try:
                response = self.socket.recv(1024).decode('ascii').strip()
            except socket.timeout:
                response = "(no response)"
            return response
        except Exception as e:
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


# ===== Lifespan =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()
    sdk_manager.initialize()
    logger.info("Server started — DB initialized, SDK manager running")
    yield
    # Shutdown
    await beyond_manager.disconnect()
    sdk_manager.shutdown()
    logger.info("Server shut down cleanly")


# Create app
app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "BEYOND Control API — SDK + PangoScript"}


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

    sdk_manager.set_points(request.point_data, request.pattern_name)
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
    sdk_manager.set_points([], "")
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
    if not ai_agent:
        raise HTTPException(status_code=503, detail="AI Agent not available. Check EMERGENT_LLM_KEY.")

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
    ai_response = await ai_agent.generate_pattern(
        user_message=request.message,
        session_id=session_id,
        history=history[:-1]  # Exclude the message we just added
    )

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


# ===== Wire Up =====
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
