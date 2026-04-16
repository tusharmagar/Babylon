from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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

# ===== Global Instances =====
sdk_manager = BeyondSDKManager()

ai_agent = None
try:
    ai_agent = BeyondAIAgent()
    logger.info("AI Agent initialized")
except Exception as e:
    logger.warning(f"AI Agent not available: {e}")


# ===== Pydantic Models =====
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
    sdk_manager.shutdown()
    logger.info("Server shut down cleanly")


# Create app
app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")


# ===== SDK / Laser Endpoints =====

@api_router.get("/")
async def root():
    return {"message": "BEYOND Control API — SDK Mode"}


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
