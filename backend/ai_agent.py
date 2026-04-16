"""
AI Agent for generating BEYOND SDK laser patterns from natural language descriptions.
Uses Anthropic Claude via emergentintegrations to convert text descriptions into
point data arrays and complete Python SDK code for the BEYOND laser system.
"""

import os
import json
import re
import logging
from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

BEYOND_SDK_SYSTEM_PROMPT = """You are an expert laser show programmer for the Pangolin BEYOND laser system. You generate point data and complete Python scripts that use the BEYOND SDK (BEYONDIOx64.dll) to render laser patterns.

## HOW THE BEYOND SDK WORKS

The DLL (BEYONDIOx64.dll) talks to BEYOND.EXE via Windows messages. BEYOND must be running. The DLL injects frames into BEYOND's rendering pipeline.

### Lifecycle (5 steps):
1. ldbCreate() → Initialize DLL
2. ldbBeyondExeReady() → Wait until BEYOND is running
3. ldbCreateZoneImage(0, "MyImage") → Create named frame buffer in zone 0
4. ldbSendFrameToImage("MyImage", ...) → Push frames (call in a loop at 30fps)
5. ldbDeleteZoneImage("MyImage") / ldbDestroy() → Cleanup

### Point Format (16 bytes per point):
- x: float32, range -32768 to +32767 (horizontal position)
- y: float32, range -32768 to +32767 (vertical position)
- z: float32, range -32768 to +32767 (usually 0)
- color: uint32, R | (G<<8) | (B<<16). 0 = blanked/invisible
- rep_count: uint8, 0-255 (corner dwell: 0=normal, 2-3=sharp corner)
- focus: uint8, always 0
- status: uint8, always 0
- zero: uint8, always 0

### Color Examples:
- Red: 0x000000FF
- Green: 0x0000FF00
- Blue: 0x00FF0000
- White: 0x00FFFFFF
- Yellow: 0x0000FFFF
- Cyan: 0x00FFFF00
- Magenta: 0x00FF00FF
- Blanked: 0x00000000

### Drawing Rules:
- There are NO "draw circle" or "draw line" commands. You send raw points.
- The laser scans through points in order, drawing visible lines between consecutive visible points.
- Circle = ~32-64 points around circumference
- Line = start + end + interpolated points
- Multiple shapes: insert blanking points (color=0) between them (3-5 blank points for travel)
- Corner dwell: set rep_count=2-3 at sharp angles for crisp corners
- Point budget: 200-600 points for clean bright output (max 8192, but more = dimmer)
- Scan rate: -30000 means 30,000 points/second

### The Send Function:
ldbSendFrameToImage(name, point_count, points_array, zone_array, rate)
- zone_array: 256 bytes, first byte = zone number (1-based), rest = 0
- rate: -30000 for 30kpps

## YOUR RESPONSE FORMAT

You MUST respond with valid JSON in this exact format:
```json
{
  "message": "A friendly explanation of what you created and how it works",
  "pattern_name": "Short name for the pattern",
  "point_data": [
    {"x": 0.0, "y": 0.0, "color": "0x00FFFFFF", "rep_count": 0},
    ...
  ],
  "python_code": "# Complete Python script as a single string with newlines"
}
```

## RULES FOR GENERATING POINT DATA:
1. Keep total points between 100-600 for bright, clean output
2. Use coordinate range of about -20000 to +20000 for good visibility (center of field)
3. Always include 3-5 blanking points (color "0x00000000") between disconnected shapes
4. Add rep_count of 2-3 at sharp corners (like triangle vertices, square corners)
5. Close shapes by returning to the first point
6. For text, use simple block-letter strokes
7. For circles, use 32-64 evenly spaced points
8. Colors should be vibrant - use full 255 values

## RULES FOR PYTHON CODE:
1. Generate a COMPLETE, runnable Python script using ctypes
2. Include the full SdkPoint struct definition
3. Include DLL loading with configurable path
4. Include the full lifecycle: create → ready → createZoneImage → loop → cleanup
5. The loop should run at 30fps using time.sleep(1/30)
6. Include proper signal handling for clean shutdown (Ctrl+C)
7. Include comments explaining each section
8. The script should be self-contained and ready to copy-paste and run on Windows
9. If the pattern involves animation (rotation, movement), implement it in the frame loop
10. Use the image name "AIPattern" for consistency

IMPORTANT: Your entire response must be valid JSON. Escape newlines in strings properly. Do not include any text outside the JSON object.
"""


class BeyondAIAgent:
    """AI Agent that generates BEYOND SDK laser patterns from natural language."""

    def __init__(self):
        self.api_key = os.environ.get('EMERGENT_LLM_KEY')
        if not self.api_key:
            raise ValueError("EMERGENT_LLM_KEY not found in environment")

    def _create_chat(self, session_id: str, history: list = None) -> LlmChat:
        """Create a new LlmChat instance with BEYOND SDK system prompt."""
        chat = LlmChat(
            api_key=self.api_key,
            session_id=session_id,
            system_message=BEYOND_SDK_SYSTEM_PROMPT
        )
        chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
        return chat

    async def generate_pattern(self, user_message: str, session_id: str, history: list = None) -> dict:
        """
        Generate a laser pattern from a natural language description.

        Args:
            user_message: The user's description of what they want to draw
            session_id: Unique session identifier
            history: List of previous messages for context

        Returns:
            Dict with message, point_data, python_code, pattern_name
        """
        try:
            chat = self._create_chat(session_id)

            # Build context from history if provided
            context_prefix = ""
            if history and len(history) > 0:
                # Build conversation context from recent messages (last 10)
                recent = history[-10:]
                context_parts = []
                for msg in recent:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        context_parts.append(f"User: {content}")
                    elif role == "assistant":
                        # Only include the message part, not the full JSON
                        ai_msg = msg.get("ai_message", content[:200])
                        context_parts.append(f"Assistant: {ai_msg}")

                if context_parts:
                    context_prefix = "Previous conversation:\n" + "\n".join(context_parts) + "\n\nNew request: "

            full_message = context_prefix + user_message

            msg = UserMessage(text=full_message)
            response = await chat.send_message(msg)

            # Parse the JSON response
            parsed = self._parse_response(response)
            return parsed

        except Exception as e:
            logger.error(f"AI agent error: {e}")
            return {
                "message": f"Sorry, I encountered an error generating your pattern: {str(e)}",
                "pattern_name": "Error",
                "point_data": [],
                "python_code": "# Error generating code. Please try again."
            }

    def _parse_response(self, response: str) -> dict:
        """Parse the AI response, extracting JSON from potential markdown wrapping."""
        try:
            # Try direct JSON parse first
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in the response
        brace_start = response.find('{')
        brace_end = response.rfind('}')
        if brace_start != -1 and brace_end != -1:
            try:
                return json.loads(response[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: return the raw text as a message
        logger.warning("Could not parse AI response as JSON, returning raw text")
        return {
            "message": response,
            "pattern_name": "Generated Pattern",
            "point_data": [],
            "python_code": "# Could not generate code for this request. Please try rephrasing."
        }
