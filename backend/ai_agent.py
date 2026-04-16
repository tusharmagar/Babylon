"""
AI Agent for generating BEYOND SDK laser patterns from natural language.
Uses OpenAI to convert text descriptions into point data arrays and
complete Python SDK code for the BEYOND laser system.
"""

import os
import json
import re
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

BEYOND_SDK_SYSTEM_PROMPT = """You generate raw laser point data for the Pangolin BEYOND SDK.

## HOW LASERS WORK
A laser scanner draws by moving a beam between points. It draws LINES between consecutive visible points. There are NO "draw circle" or "draw line" commands — you must output every point along every line.

## POINT FORMAT
Each point: {"x": float, "y": float, "color": integer, "rep_count": integer}
- x, y: coordinates from -15000 to +15000.
- color: packed uint32 = R + G*256 + B*65536. Color 0 = BLANKED (laser off during travel).
- rep_count: 0 normal, 2 at sharp corners for dwell.

## COLORS (exact integer values)
WHITE=16777215  RED=255  GREEN=65280  BLUE=16711680  YELLOW=65535  CYAN=16776960  MAGENTA=16711935  BLANKED=0

## CRITICAL DRAWING RULES
1. You MUST interpolate points along every line/edge. A line from A to B needs 8-15 intermediate points, NOT just the two endpoints. Without interpolation, the laser just shows dots.
2. Circle = 48-64 evenly spaced points around the circumference. Close by repeating the first point.
3. Star = for each of the 10 line segments connecting vertices, output 10 interpolated points along that line. A 5-point star needs ~100+ points total.
4. Triangle = 3 edges x 10 points per edge = 30+ points.
5. Sharp corners: add rep_count=2 at vertices so corners look crisp.
6. Multiple shapes: insert 3 blanking points (color: 0) between them for galvo travel.
7. Budget: 100-500 points total. Fewer = brighter.
8. First point must have color > 0 (visible). Only use color=0 for blanking gaps.

## EXAMPLE: Triangle (correct)
A triangle has 3 vertices. For each edge, interpolate ~10 points:
- Edge 1: vertex A to vertex B (10 points along the line)
- Add rep_count=2 at vertex B (corner dwell)
- Edge 2: vertex B to vertex C (10 points)
- Add rep_count=2 at vertex C
- Edge 3: vertex C back to vertex A (10 points)
Total: ~33 points. NOT just 3 points.

## EXAMPLE: Star (correct)
A 5-point star has 5 outer vertices and 5 inner vertices, connected alternately.
For each of the 10 line segments, output 8-10 interpolated points.
Total: ~100 points. NOT just 10 vertices.

## RESPONSE FORMAT (strict JSON)
{"message": "what you made", "pattern_name": "short_name", "point_data": [...], "python_code": "# standalone script"}

RULES:
- color MUST be integer, NEVER a string
- ALWAYS interpolate between vertices — never output just the vertices alone
- Minimum 50 points for any shape, more for complex ones"""


class BeyondAIAgent:
    """AI Agent that generates BEYOND SDK laser patterns from natural language."""

    def __init__(self):
        self.api_key = os.environ.get('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = AsyncOpenAI(api_key=self.api_key)

    async def generate_pattern(self, user_message: str, session_id: str, history: list = None) -> dict:
        try:
            messages = [{"role": "system", "content": BEYOND_SDK_SYSTEM_PROMPT}]

            # Build conversation history if provided
            if history and len(history) > 0:
                recent = history[-10:]
                for msg in recent:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        messages.append({"role": "user", "content": content})
                    elif role == "assistant":
                        ai_msg = msg.get("ai_message", content[:200])
                        messages.append({"role": "assistant", "content": ai_msg})

            messages.append({"role": "user", "content": user_message})

            logger.info(f"AI: Calling gpt-5.4 with {len(messages)} messages...")

            response = await self.client.chat.completions.create(
                model="gpt-5.4",
                messages=messages,
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            response_text = response.choices[0].message.content
            logger.info(f"AI: Got response ({len(response_text)} chars), usage: {response.usage}")

            # Parse the JSON response
            parsed = self._parse_response(response_text)

            # Ensure colors are integers, not strings
            if parsed.get("point_data"):
                for p in parsed["point_data"]:
                    color = p.get("color", 0)
                    if isinstance(color, str):
                        p["color"] = int(color, 16) if color.startswith("0x") else int(color)

            logger.info(f"AI: Parsed — pattern={parsed.get('pattern_name')!r}, "
                        f"points={len(parsed.get('point_data', []))}, "
                        f"has_code={bool(parsed.get('python_code'))}")

            # Validate and log points
            pts = parsed.get("point_data", [])
            if pts:
                visible = [p for p in pts if p.get("color", 0) != 0]
                blanked = len(pts) - len(visible)
                logger.info(f"AI: {len(visible)} visible pts, {blanked} blanked pts")
                if visible:
                    logger.info(f"AI: First visible: {visible[0]}")
                else:
                    logger.warning("AI: ALL POINTS ARE BLANKED (color=0)! Pattern will be invisible!")

            return parsed

        except Exception as e:
            logger.error(f"AI agent error: {type(e).__name__}: {e}", exc_info=True)
            return {
                "message": f"Error generating pattern: {str(e)}",
                "pattern_name": "Error",
                "point_data": [],
                "python_code": "# Error generating code. Please try again."
            }

    def _parse_response(self, response: str) -> dict:
        """Parse the AI response JSON."""
        try:
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

        logger.warning(f"Could not parse AI response as JSON: {response[:200]}")
        return {
            "message": response,
            "pattern_name": "Generated Pattern",
            "point_data": [],
            "python_code": "# Could not parse response. Please try rephrasing."
        }
