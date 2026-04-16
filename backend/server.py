from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import socket
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== TCP Connection Manager for BEYOND =====
class BeyondConnectionManager:
    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.host: Optional[str] = None
        self.port: Optional[int] = None
        self.connected: bool = False
        self.lock = asyncio.Lock()
        self.command_logs: List[dict] = []
        self.max_logs = 100
        self.echo_mode = 1  # Default: returns OK/ERROR
        
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
                # Close existing connection if any
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None
                    self.connected = False
                
                self.host = host
                self.port = port
                
                # Create TCP socket
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(timeout)
                
                # Connect to BEYOND TCP server (via ngrok or direct)
                self.socket.connect((host, port))
                self.connected = True
                
                self.add_log("CONNECTION", f"Connected to {host}:{port}")
                
                # Set echo mode for proper response handling
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
        """Internal send without lock - must be called within lock context"""
        if not self.socket or not self.connected:
            return None
        
        try:
            # PangoScript commands must end with \r\n
            full_command = f"{command}\r\n"
            self.socket.sendall(full_command.encode('ascii'))
            
            # Try to read response
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
        """Send a PangoScript command and get response"""
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


# Global connection manager instance
beyond_manager = BeyondConnectionManager()


# ===== Pydantic Models =====
class ConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    host: str
    port: int
    timeout: float = 5.0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class ConnectionConfigCreate(BaseModel):
    host: str
    port: int
    timeout: float = 5.0

class CommandRequest(BaseModel):
    command: str

class CueRequest(BaseModel):
    page: int = 1
    cue: int

class StatusResponse(BaseModel):
    connected: bool
    host: Optional[str]
    port: Optional[int]
    echo_mode: int

class CommandResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    log: Optional[dict] = None


# ===== Lifespan for startup/shutdown =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load last saved config and try to connect
    try:
        config = await db.beyond_config.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        if config:
            logger.info(f"Found saved config: {config['host']}:{config['port']}")
            # Don't auto-connect, let user trigger manually
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    
    yield
    
    # Shutdown: Disconnect and close MongoDB
    await beyond_manager.disconnect()
    client.close()


# Create the main app
app = FastAPI(lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ===== API Endpoints =====

@api_router.get("/")
async def root():
    return {"message": "Pangolin BEYOND Control API"}


# Connection Configuration
@api_router.get("/config")
async def get_config():
    """Get the current/saved connection configuration"""
    config = await db.beyond_config.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    if config:
        return config
    return {"host": "", "port": 16063, "timeout": 5.0}


@api_router.post("/config")
async def save_config(config: ConnectionConfigCreate):
    """Save connection configuration"""
    config_obj = ConnectionConfig(
        host=config.host,
        port=config.port,
        timeout=config.timeout
    )
    doc = config_obj.model_dump()
    await db.beyond_config.insert_one(doc)
    # Return the config without MongoDB ObjectId
    return {"success": True, "config": {
        "id": doc["id"],
        "host": doc["host"],
        "port": doc["port"],
        "timeout": doc["timeout"],
        "created_at": doc["created_at"]
    }}


# Connection Management
@api_router.post("/connect")
async def connect_beyond(config: ConnectionConfigCreate):
    """Connect to BEYOND via TCP (through ngrok endpoint)"""
    # Save config first
    config_obj = ConnectionConfig(
        host=config.host,
        port=config.port,
        timeout=config.timeout
    )
    doc = config_obj.model_dump()
    await db.beyond_config.insert_one(doc)
    
    # Attempt connection
    success = await beyond_manager.connect(config.host, config.port, config.timeout)
    
    if success:
        return {"success": True, "message": f"Connected to {config.host}:{config.port}"}
    else:
        raise HTTPException(status_code=503, detail=f"Failed to connect to {config.host}:{config.port}")


@api_router.post("/disconnect")
async def disconnect_beyond():
    """Disconnect from BEYOND"""
    await beyond_manager.disconnect()
    return {"success": True, "message": "Disconnected"}


@api_router.get("/status")
async def get_status():
    """Get current connection status"""
    return beyond_manager.get_status()


@api_router.post("/test-connection")
async def test_connection():
    """Test the current connection by sending a simple command"""
    if not beyond_manager.connected:
        return {"success": False, "error": "Not connected"}
    
    # Send a harmless command to test connection
    result = await beyond_manager.send_command("Hello")
    return result


# PangoScript Commands
@api_router.post("/command", response_model=CommandResponse)
async def send_command(request: CommandRequest):
    """Send a raw PangoScript command"""
    result = await beyond_manager.send_command(request.command)
    return CommandResponse(**result)


@api_router.post("/cue/start", response_model=CommandResponse)
async def start_cue(request: CueRequest):
    """Start a specific cue (1-indexed)"""
    # BEYOND uses 1-indexed cues: StartCue page,cue
    command = f"StartCue {request.page},{request.cue}"
    result = await beyond_manager.send_command(command)
    return CommandResponse(**result)


@api_router.post("/cue/stop", response_model=CommandResponse)
async def stop_cue(request: CueRequest):
    """Stop a specific cue"""
    command = f"StopCue {request.page},{request.cue}"
    result = await beyond_manager.send_command(command)
    return CommandResponse(**result)


@api_router.post("/stop-all", response_model=CommandResponse)
async def stop_all():
    """Stop all playback immediately"""
    result = await beyond_manager.send_command("StopAllNow")
    return CommandResponse(**result)


@api_router.post("/blackout/on", response_model=CommandResponse)
async def blackout_on():
    """Enable blackout (disable laser output)"""
    result = await beyond_manager.send_command("DisableLaserOutput")
    return CommandResponse(**result)


@api_router.post("/blackout/off", response_model=CommandResponse)
async def blackout_off():
    """Disable blackout (enable laser output)"""
    result = await beyond_manager.send_command("EnableLaserOutput")
    return CommandResponse(**result)


@api_router.post("/blackout/toggle", response_model=CommandResponse)
async def blackout_toggle():
    """Toggle blackout state"""
    result = await beyond_manager.send_command("ToggleBlackout")
    return CommandResponse(**result)


# Command Logs
@api_router.get("/logs")
async def get_logs(limit: int = 50):
    """Get recent command logs"""
    return {"logs": beyond_manager.get_logs(limit)}


@api_router.delete("/logs")
async def clear_logs():
    """Clear command logs"""
    beyond_manager.command_logs = []
    return {"success": True, "message": "Logs cleared"}


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
