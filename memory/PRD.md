# Pangolin BEYOND Laser Control System - PRD

## Original Problem Statement
Build a full-stack app to control Pangolin BEYOND laser software via PangoScript TCP interface through ngrok-exposed remote TCP endpoint. The system must:
- Send ASCII PangoScript commands terminated by \r\n
- Handle responses and two-way communication
- Treat BEYOND cues as 1-indexed
- Provide a UI with 20 cue buttons, connection settings, and master controls

## User Choices
- Connection Configuration: Settings page in UI (can be changed anytime)
- Authentication: No authentication needed
- Cue Buttons: Just simple buttons to trigger cues
- Design: No specific preferences (can be changed later)

## Architecture

### Backend (FastAPI)
- **TCP Connection Manager**: Handles socket connection to BEYOND via configurable host:port
- **PangoScript Command Layer**: Sends commands with \r\n termination, handles responses
- **MongoDB Storage**: Persists connection configuration
- **REST API Endpoints**:
  - `/api/config` - GET/POST connection configuration
  - `/api/connect` - Establish TCP connection
  - `/api/disconnect` - Close TCP connection
  - `/api/status` - Get connection status
  - `/api/cue/start` - Start a cue (1-indexed)
  - `/api/cue/stop` - Stop a cue
  - `/api/stop-all` - StopAllNow command
  - `/api/blackout/on|off|toggle` - Laser output control
  - `/api/command` - Send raw PangoScript
  - `/api/logs` - Get/clear command logs

### Frontend (React)
- Dark theme "Control Room" UI
- 20 cue buttons in 5x4 grid
- Connection status indicator with pulsing dot
- Settings dialog for host/port configuration
- Master controls: STOP ALL, BLACKOUT
- Terminal-style command log panel

## What's Been Implemented (April 16, 2026)

### MVP Complete
- [x] Backend TCP connection manager with configurable host:port
- [x] All PangoScript command endpoints (StartCue, StopCue, StopAllNow, blackout)
- [x] MongoDB configuration persistence
- [x] Command logging system
- [x] Frontend with 20 cue trigger buttons
- [x] Settings dialog for ngrok endpoint configuration
- [x] Connection status indicator (online/offline with pulsing animation)
- [x] Master controls (Stop All, Blackout toggle)
- [x] Command log panel with terminal styling
- [x] All tests passing (100% backend, 100% frontend, 100% integration)

### AI Builder Feature (New)
- [x] AI Chat Agent using Anthropic Claude via emergentintegrations
- [x] System prompt with comprehensive BEYOND SDK documentation
- [x] Generates point data arrays (x, y, color, rep_count) from natural language
- [x] Generates complete Python scripts using ctypes + BEYONDIOx64.dll
- [x] Chat session management with MongoDB persistence (CRUD)
- [x] Tabbed UI layout: Cues | AI Builder
- [x] Chat interface with sessions sidebar, suggestion chips
- [x] Laser Preview canvas with glow effects rendering point data
- [x] Code viewer panel with copy/download functionality
- [x] Conversation history support for multi-turn interactions

## Prioritized Backlog

### P0 (Next)
- Real connection testing with actual BEYOND + ngrok setup
- Cue status feedback (which cue is currently playing)

### P1
- Multiple page support (currently only Page 1)
- Custom cue labels/names
- BPM control slider
- Raw command input field

### P2
- Save/load cue presets
- Keyboard shortcuts for cues
- Mobile-responsive design improvements
- WebSocket for real-time updates

## Technology Stack
- Backend: FastAPI, Motor (MongoDB async), Python sockets
- Frontend: React, Tailwind CSS, Shadcn/UI components
- Database: MongoDB
- Fonts: Chivo (headings), IBM Plex Sans (body), JetBrains Mono (terminal)
