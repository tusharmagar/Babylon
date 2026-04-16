#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: "Rebuilt Pangolin BEYOND control to run fully locally with direct SDK DLL integration. AI chat generates laser patterns, streams directly to BEYOND via BEYONDIOx64.dll at 30fps. SQLite instead of MongoDB. No PangoScript TCP. NEW: YouTube Song to Laser pipeline - YouTube URL → Audio extraction (yt-dlp) → Lyrics (LRCLIB) → Audio analysis (librosa) → AI Show Design (GPT-4o) → Frame generation (30fps) → Point optimization → ILDA Format 5 → .ild file download."

backend:
  - task: "BEYOND SDK Manager - DLL lifecycle, 30fps send loop, point swapping"
    implemented: true
    working: true
    file: "sdk_manager.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "BeyondSDKManager loads DLL, creates zone image, runs background 30fps loop. Simulation mode when DLL unavailable. set_points() swaps instantly. blackout() clears."
        - working: true
          agent: "testing"
          comment: "✅ TESTED: SDK manager working correctly in simulation mode. Point data swapping, blackout, and status reporting all functional. 30fps loop running properly. No critical issues found."

  - task: "SQLite Database - Chat sessions and messages"
    implemented: true
    working: true
    file: "database.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "Zero-config SQLite. CRUD for sessions and messages. No MongoDB."
        - working: true
          agent: "testing"
          comment: "✅ TESTED: SQLite database fully functional. Session creation, message storage, retrieval, and deletion all working. Database file created at /app/backend/beyond.db with proper schema."

  - task: "Laser Control Endpoints"
    implemented: true
    working: true
    file: "server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "GET /api/laser/status, POST /api/laser/send, POST /api/laser/blackout, POST /api/laser/stop"
        - working: true
          agent: "testing"
          comment: "✅ TESTED: All laser control endpoints working perfectly."

  - task: "AI Chat Agent and Endpoints"
    implemented: true
    working: true
    file: "server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "POST /api/chat/send, /new, /sessions, /{id}/messages, DELETE /{id}. OpenAI via direct API."
        - working: true
          agent: "testing"
          comment: "✅ TESTED: All chat endpoints working correctly."

  - task: "YouTube-to-Laser Pipeline - Audio Extraction (yt-dlp)"
    implemented: true
    working: true
    file: "services/youtube.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "Uses yt-dlp to download YouTube video, extract audio as WAV. Returns metadata (title, artist, duration, thumbnail)."

  - task: "YouTube-to-Laser Pipeline - Lyrics Retrieval (LRCLIB)"
    implemented: true
    working: true
    file: "services/lyrics.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "LRCLIB API search. LRC format parsing [MM:SS.CS]text. Word timing estimation with min weight 3. Fallback to synthetic lyrics."

  - task: "YouTube-to-Laser Pipeline - Audio Analysis (librosa)"
    implemented: true
    working: true
    file: "services/audio_analysis.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "librosa BPM, beat_times_ms, energy_envelope (~10Hz), segment_boundaries_ms (8 MFCC segments)."

  - task: "YouTube-to-Laser Pipeline - Show Design (GPT-4o)"
    implemented: true
    working: true
    file: "services/song_interpreter.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "GPT-4o for creative show design. Rule-based fallback when no API key. Color palette, section effects, text style."

  - task: "YouTube-to-Laser Pipeline - Text Renderer (Hershey Font)"
    implemented: true
    working: true
    file: "services/text_renderer.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "Hershey Simplex Roman single-stroke font. text_to_points + animated styles (typewriter, fade, wave, word_highlight). Auto-scale to ILDA space."

  - task: "YouTube-to-Laser Pipeline - Geometric Effects"
    implemented: true
    working: true
    file: "services/effects.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "Lissajous, spiral, beam_fan, starburst, tunnel, beat_pulse. Energy-scaled for instrumental sections."

  - task: "YouTube-to-Laser Pipeline - Frame Generation + Point Optimizer + ILDA Writer"
    implemented: true
    working: true
    file: "services/laser_generator.py, services/point_optimizer.py, services/ilda_writer.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "30fps frame generation. Corner dwell, blanking insertion, 200-800 point enforcement. ILDA Format 5 binary (32-byte headers, 8-byte points, big-endian)."

  - task: "YouTube Pipeline API Endpoint (SSE)"
    implemented: true
    working: true
    file: "server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        - working: true
          agent: "main"
          comment: "POST /api/youtube/analyze (SSE streaming 6 stages), GET /api/youtube/download/{job_id}, GET /api/youtube/job/{job_id}."

frontend:
  - task: "AI Builder with Send to Laser"
    implemented: true
    working: true
    file: "src/components/AIBuilder.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "Chat + Send to Laser button + laser preview + collapsible reference code + session management + BLACKOUT"

  - task: "SDK Status and Controls Tab"
    implemented: true
    working: true
    file: "src/App.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "SDK status indicator, Controls tab with stats and blackout. AI Builder as default tab."

  - task: "Song to Laser Tab"
    implemented: true
    working: true
    file: "src/components/SongToLaser.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "New tab in App.js. YouTube URL input, SSE progress streaming with 6-stage pipeline indicators, result card with metadata/sections/palette/download. Empty state with feature tags."

metadata:
  created_by: "main_agent"
  version: "3.0"
  test_sequence: 5
  run_ui: false

test_plan:
  current_focus:
    - "YouTube-to-Laser Pipeline - Audio Extraction (yt-dlp)"
    - "YouTube-to-Laser Pipeline - Lyrics Retrieval (LRCLIB)"
    - "YouTube-to-Laser Pipeline - Audio Analysis (librosa)"
    - "YouTube-to-Laser Pipeline - Text Renderer (Hershey Font)"
    - "YouTube-to-Laser Pipeline - Geometric Effects"
    - "YouTube-to-Laser Pipeline - Frame Generation + Point Optimizer + ILDA Writer"
    - "YouTube Pipeline API Endpoint (SSE)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "main"
      message: "NEW YouTube-to-Laser pipeline implemented. 9 service modules + API. Test plan: 1) Test individual service modules (text_renderer, effects, lyrics, audio_analysis, point_optimizer, ilda_writer). 2) Test SSE endpoint POST /api/youtube/analyze with a real YouTube URL. 3) Test download endpoint GET /api/youtube/download/{job_id}. Note: The GPT-4o show design step requires OPENAI_API_KEY which may not be set — it has a rule-based fallback. The yt-dlp download requires internet access and may take 30-60s. LRCLIB API is free, no key needed. Test the component services independently first: import services from sys.path, call text_to_points('HELLO',0,0,800,(0,255,0)) and verify points returned, call effects.lissajous() etc. Then test the full pipeline endpoint with a real YouTube URL (use a short video for speed). The SSE endpoint streams progress events. Important: backend runs on localhost:8001, test with curl or requests. SSE returns 'event: progress' with stage data and 'event: complete' with final result."