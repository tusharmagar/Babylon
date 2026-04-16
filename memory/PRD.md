# Pangolin BEYOND Laser Control System - PRD

## Problem Statement
Build a fully local application that lets users describe laser patterns in natural language, and have an AI agent generate and stream them directly to Pangolin BEYOND via the SDK DLL at 30fps.

## Architecture

### Backend (FastAPI + SQLite)
- **BEYOND SDK Manager** (`sdk_manager.py`): Loads `BEYONDIOx64.dll` via ctypes, creates one zone image at startup, runs continuous 30fps background thread. AI swaps point data instantly.
- **AI Agent** (`ai_agent.py`): Anthropic Claude converts natural language → point data + reference Python code
- **SQLite Database** (`database.py`): Zero-config chat history persistence
- **REST API**:
  - `GET /api/laser/status` — SDK status, streaming info
  - `POST /api/laser/send` — Stream point data to BEYOND
  - `POST /api/laser/blackout` — Clear laser
  - `POST /api/laser/stop` — Stop streaming
  - `POST /api/chat/send` — AI generates pattern
  - `POST /api/chat/new` — New session
  - `GET /api/chat/sessions` — List sessions
  - `GET /api/chat/{id}/messages` — Get messages
  - `DELETE /api/chat/{id}` — Delete session

### Frontend (React + Tailwind)
- **AI Builder** (default tab): Chat interface with "Send to Laser" button, laser preview canvas, collapsible reference code
- **Controls** tab: SDK status dashboard and BLACKOUT button
- **Laser Preview**: Canvas renders point data with laser glow effects
- **Session sidebar**: Chat history management

## How It Works
1. User describes pattern → "Draw a spinning star"
2. AI generates point data (x, y, color, rep_count tuples) + explanation
3. Laser preview shows what it looks like
4. User clicks "Send to Laser" → backend swaps point list in SDK manager
5. Background thread sends new points to BEYOND on the very next frame
6. Pattern change is instant — no restart, no reconnect

## Key Technical Details
- DLL path: `C:\Program Files\MadMapper 5.7.1\BEYONDIOx64.dll`
- One zone image ("AgentOutput") for the whole session
- 30fps send loop, 30,000 pps scan rate
- Simulation mode when DLL unavailable (cloud/Linux)
- No MongoDB, no PangoScript TCP — just SDK DLL + SQLite

## Technology Stack
- Backend: FastAPI, SQLite, ctypes (DLL), emergentintegrations (Anthropic Claude)
- Frontend: React, Tailwind CSS, Shadcn/UI, Canvas API
- LLM: Anthropic Claude via Emergent LLM Key
