"""AI agent that turns natural-language prompts into laser patterns.

Design: the LLM never outputs coordinates. It picks primitives (circle,
star, polygon, …) via tool calls; this module executes them deterministically
and composes a single frame. Streaming is end-to-end — reasoning tokens,
tool calls, and final text are all surfaced as SSE events.
"""

import os
import json
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional

from openai import AsyncOpenAI

from services import laser_primitives as lp

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a laser-show designer controlling a Pangolin BEYOND laser.

You DO NOT output coordinates. You call primitive drawing tools (circle, star, polygon,
line, rectangle, spiral, heart, text). The backend renders them into laser points.

COORDINATE SPACE
- Origin (0, 0) is center of the scan field.
- Extents: x,y ∈ [-15000, 15000]. Stay inside ±14000 for safe margin.
- Positive y is up.

STATIC vs ANIMATED PATTERNS
- By default everything you draw goes into a single frame that loops forever.
- For animation (countdowns, sequences, blinks, transitions), call `next_scene(hold_ms)`
  after each frame. Everything after the call goes into the next frame.
- Example — countdown 3, 2, 1:
    draw_text("3", cx=0, cy=0, size=6000, color="red")
    next_scene(hold_ms=1000)
    draw_text("2", cx=0, cy=0, size=6000, color="yellow")
    next_scene(hold_ms=1000)
    draw_text("1", cx=0, cy=0, size=6000, color="green")
    next_scene(hold_ms=1000)   # final scene still needs its hold time
- A blinking shape: draw it, next_scene(500), next_scene(500) (empty scene = off).

DESIGN RULES
- Keep each scene simple: 1-4 shapes looks crisp, more gets messy on a laser.
- Pick bold saturated colors — pastels look weak. Use "red", "green", "blue",
  "yellow", "cyan", "magenta", "white", "orange", "pink", "purple".
- Reasonable sizes: shapes 3000-10000 units wide generally look best.
- For text: size 3000-8000 is readable. All-caps renders best.

WHEN DONE
Send a short final message (1 sentence) telling the user what you made.
If the user's request is ambiguous, make a reasonable choice and go.
"""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "draw_circle",
            "description": "Draw a circle. Use for 'o', moon, sun, ring, wheel, bubble.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number", "description": "Center x (-14000 to 14000)"},
                    "cy": {"type": "number", "description": "Center y (-14000 to 14000)"},
                    "radius": {"type": "number", "description": "Radius (500-12000)"},
                    "color": {"type": "string", "description": "Color name (red, green, blue, yellow, cyan, magenta, white, orange, pink, purple)"},
                },
                "required": ["cx", "cy", "radius", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_star",
            "description": "Draw an N-pointed star. Classic 5-point star looks iconic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "outer_radius": {"type": "number", "description": "Size (1500-10000)"},
                    "points": {"type": "integer", "description": "Number of points (3-12)"},
                    "color": {"type": "string"},
                    "inner_ratio": {"type": "number", "description": "0.3-0.5 for classic star, lower = pointier"},
                    "rotation_deg": {"type": "number"},
                },
                "required": ["cx", "cy", "outer_radius", "points", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_polygon",
            "description": "Regular polygon (triangle=3, square=4, hexagon=6).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "radius": {"type": "number"},
                    "sides": {"type": "integer", "description": "3-24"},
                    "color": {"type": "string"},
                    "rotation_deg": {"type": "number"},
                },
                "required": ["cx", "cy", "radius", "sides", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_line",
            "description": "Straight line from (x1,y1) to (x2,y2).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "x2": {"type": "number"},
                    "y2": {"type": "number"},
                    "color": {"type": "string"},
                },
                "required": ["x1", "y1", "x2", "y2", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_rectangle",
            "description": "Rectangle (optionally rotated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                    "color": {"type": "string"},
                    "rotation_deg": {"type": "number"},
                },
                "required": ["cx", "cy", "width", "height", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_spiral",
            "description": "Archimedean spiral outward from center.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "max_radius": {"type": "number"},
                    "turns": {"type": "number", "description": "Number of revolutions (1-10)"},
                    "color": {"type": "string"},
                },
                "required": ["cx", "cy", "max_radius", "turns", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_heart",
            "description": "Heart shape.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "size": {"type": "number", "description": "Overall size (2000-10000)"},
                    "color": {"type": "string"},
                },
                "required": ["cx", "cy", "size", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_text",
            "description": "Draw uppercase text/digits with a stroke font. Great for countdowns, labels, words.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Short text — kept short (1-6 chars is best)"},
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "size": {"type": "number", "description": "Glyph height (3000-8000 looks best)"},
                    "color": {"type": "string"},
                },
                "required": ["text", "cx", "cy", "size", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "next_scene",
            "description": "Close the current scene and start a new one. Everything drawn after this lives in the next frame. Use for animations (countdowns, blinking, sequences).",
            "parameters": {
                "type": "object",
                "properties": {
                    "hold_ms": {"type": "integer", "description": "How long to display the scene you just finished, in milliseconds (e.g. 1000 for 1s)"},
                },
                "required": ["hold_ms"],
            },
        },
    },
]


def _execute_draw_tool(name: str, args: dict) -> List[dict]:
    """Run one drawing tool and return its point list."""
    if name == "draw_circle":
        return lp.draw_circle(args["cx"], args["cy"], args["radius"], args["color"])
    if name == "draw_star":
        return lp.draw_star(
            args["cx"], args["cy"], args["outer_radius"], args["points"], args["color"],
            inner_ratio=args.get("inner_ratio", 0.4),
            rotation_deg=args.get("rotation_deg", -90.0),
        )
    if name == "draw_polygon":
        return lp.draw_polygon(
            args["cx"], args["cy"], args["radius"], args["sides"], args["color"],
            rotation_deg=args.get("rotation_deg", 0.0),
        )
    if name == "draw_line":
        return lp.draw_line(args["x1"], args["y1"], args["x2"], args["y2"], args["color"])
    if name == "draw_rectangle":
        return lp.draw_rectangle(
            args["cx"], args["cy"], args["width"], args["height"], args["color"],
            rotation_deg=args.get("rotation_deg", 0.0),
        )
    if name == "draw_spiral":
        return lp.draw_spiral(
            args["cx"], args["cy"], args["max_radius"], args["color"],
            turns=args.get("turns", 3.0),
        )
    if name == "draw_heart":
        return lp.draw_heart(args["cx"], args["cy"], args["size"], args["color"])
    if name == "draw_text":
        return lp.draw_text(args["text"], args["cx"], args["cy"], args["size"], args["color"])
    raise ValueError(f"Unknown drawing tool: {name}")


class BeyondAIAgent:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = os.environ.get("OPENAI_MODEL", "gpt-5.4")

    async def stream_pattern(
        self,
        user_message: str,
        history: Optional[List[dict]] = None,
    ) -> AsyncGenerator[dict, None]:
        """Yield SSE-ready events as the model streams.

        Event types:
          - thinking:   {"type": "thinking", "delta": str}   (reasoning token text)
          - tool_start: {"type": "tool_start", "name": str}
          - tool_done:  {"type": "tool_done", "name": str, "args": dict, "point_count": int}
          - message:    {"type": "message", "delta": str}    (assistant-visible text)
          - final:      {"type": "final", "pattern_name": str, "point_data": [...], "message": str}
          - error:      {"type": "error", "error": str}
        """
        messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            for m in history[-10:]:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content[:500]})
        messages.append({"role": "user", "content": user_message})

        # Scene tracking. `current_scene_points` accumulates shapes until the
        # agent calls `next_scene`, which pushes it onto `scenes` with a hold
        # duration. If the agent never calls next_scene, we end up with one
        # scene = a static pattern.
        current_scene_points: List[dict] = []
        scenes: List[List[dict]] = []
        scene_durations_ms: List[int] = []
        assistant_text_parts: List[str] = []

        def _append_shape_to_scene(shape_pts: List[dict]) -> None:
            if not shape_pts:
                return
            if current_scene_points:
                sx, sy = shape_pts[0]["x"], shape_pts[0]["y"]
                for _ in range(3):
                    current_scene_points.append(
                        {"x": sx, "y": sy, "color": 0, "rep_count": 0}
                    )
            current_scene_points.extend(shape_pts)

        try:
            # Loop: allow model to tool-call, we execute, feed results back, until final text
            for turn in range(6):
                logger.info(f"AI: turn {turn + 1} — {len(messages)} msgs in context")
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    stream=True,
                )

                tool_calls_by_idx: Dict[int, dict] = {}
                turn_text_parts: List[str] = []
                finish_reason: Optional[str] = None

                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta

                    # Reasoning / thinking deltas (if the provider exposes them)
                    reasoning_text = getattr(delta, "reasoning_content", None) or \
                                     getattr(delta, "reasoning", None)
                    if reasoning_text:
                        yield {"type": "thinking", "delta": reasoning_text}

                    # Plain assistant text
                    if delta.content:
                        turn_text_parts.append(delta.content)
                        yield {"type": "message", "delta": delta.content}

                    # Streaming tool-call deltas — accumulate by index
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            slot = tool_calls_by_idx.setdefault(tc.index, {
                                "id": None, "name": "", "args_str": ""
                            })
                            if tc.id:
                                slot["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    # First time we see the name → notify
                                    if not slot["name"]:
                                        yield {"type": "tool_start", "name": tc.function.name}
                                    slot["name"] = tc.function.name
                                if tc.function.arguments:
                                    slot["args_str"] += tc.function.arguments

                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

                logger.info(
                    f"AI: turn {turn + 1} done — finish={finish_reason!r}, "
                    f"tool_calls={len(tool_calls_by_idx)}, "
                    f"text_chars={sum(len(p) for p in turn_text_parts)}"
                )

                # Append the assistant turn
                if tool_calls_by_idx:
                    assistant_msg = {
                        "role": "assistant",
                        "content": "".join(turn_text_parts) or None,
                        "tool_calls": [
                            {
                                "id": slot["id"],
                                "type": "function",
                                "function": {
                                    "name": slot["name"],
                                    "arguments": slot["args_str"] or "{}",
                                },
                            }
                            for slot in tool_calls_by_idx.values() if slot["id"]
                        ],
                    }
                    messages.append(assistant_msg)

                    # Execute each tool call and feed results back
                    for slot in tool_calls_by_idx.values():
                        if not slot["id"]:
                            continue
                        try:
                            args = json.loads(slot["args_str"] or "{}")
                        except json.JSONDecodeError:
                            args = {}

                        point_count = 0
                        tool_status = "ok"
                        tool_summary = ""

                        try:
                            if slot["name"] == "next_scene":
                                hold_ms = int(args.get("hold_ms", 1000))
                                # Push current scene (may be empty, that's a valid "off" frame)
                                scenes.append(list(current_scene_points))
                                scene_durations_ms.append(max(50, hold_ms))
                                point_count = len(current_scene_points)
                                current_scene_points.clear()
                                tool_summary = f"scene #{len(scenes)} held for {hold_ms}ms"
                            else:
                                shape_pts = _execute_draw_tool(slot["name"], args)
                                _append_shape_to_scene(shape_pts)
                                point_count = len(shape_pts)
                                tool_summary = f"{point_count} points added"
                        except Exception as e:
                            tool_status = "error"
                            tool_summary = str(e)
                            logger.warning(f"Tool {slot['name']} failed: {e}")

                        yield {
                            "type": "tool_done",
                            "name": slot["name"],
                            "args": args,
                            "point_count": point_count,
                        }

                        messages.append({
                            "role": "tool",
                            "tool_call_id": slot["id"],
                            "content": json.dumps({
                                "status": tool_status,
                                "summary": tool_summary,
                                "scene_count": len(scenes),
                            }),
                        })

                    if finish_reason != "tool_calls":
                        # Model finished with tools but also ended — loop again to let it speak
                        continue
                    # Go round again — model will now usually emit a final text message
                    continue

                # No tool calls this turn → we have final text
                if turn_text_parts:
                    assistant_text_parts.extend(turn_text_parts)
                break

            # Flush any pending scene that wasn't closed by a next_scene call.
            # If we have prior scenes, treat this as the last frame with a
            # sensible default hold. Otherwise it's a static pattern.
            if scenes and current_scene_points:
                scenes.append(list(current_scene_points))
                scene_durations_ms.append(1000)
                current_scene_points.clear()

            final_message = "".join(assistant_text_parts).strip() or "Pattern ready."
            pattern_name = final_message[:60] or "AI Pattern"

            if scenes:
                total_ms = sum(scene_durations_ms)
                logger.info(
                    f"AI: yielding final animation — {len(scenes)} scenes, "
                    f"{total_ms}ms total, msg={final_message[:80]!r}"
                )
                yield {
                    "type": "final",
                    "pattern_name": pattern_name,
                    "animated": True,
                    "scenes": scenes,
                    "durations_ms": scene_durations_ms,
                    "point_data": scenes[0] if scenes else [],  # preview uses frame 0
                    "message": final_message,
                }
            else:
                logger.info(
                    f"AI: yielding final static — {len(current_scene_points)} points, "
                    f"msg={final_message[:80]!r}"
                )
                yield {
                    "type": "final",
                    "pattern_name": pattern_name,
                    "animated": False,
                    "point_data": current_scene_points,
                    "message": final_message,
                }

        except Exception as e:
            logger.error(f"AI agent error: {e}", exc_info=True)
            yield {"type": "error", "error": f"{type(e).__name__}: {e}"}
