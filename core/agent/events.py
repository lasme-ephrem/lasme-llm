"""Typed agent events — the single contract between backend and UI.

Every observable step of an agent run is an ``AgentEvent`` with a stable
``type``. The chat UI renders a timeline from these; they are persisted
with the message so a run can be replayed without the model.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

TURN_START = "turn_start"
REASONING_DELTA = "reasoning_delta"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
CONTENT_DELTA = "content_delta"
FINAL = "final"
TURN_END = "turn_end"
AGENT_ERROR = "agent_error"


@dataclass
class AgentEvent:
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "ts": round(self.ts, 3), **self.payload}

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


class EventLog:
    """Collects events of one run; consumed for persistence and replay."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def add(self, type: str, **payload: Any) -> AgentEvent:
        event = AgentEvent(type=type, payload=payload)
        self.events.append(event)
        return event

    def to_list(self) -> list[Dict[str, Any]]:
        return [event.to_dict() for event in self.events]

    def usage_totals(self) -> Dict[str, int]:
        prompt = completion = 0
        for event in self.events:
            if event.type == TURN_END:
                prompt += int(event.payload.get("prompt_tokens") or 0)
                completion += int(event.payload.get("output_tokens") or 0)
        return {"prompt_tokens": prompt, "output_tokens": completion}

    def tool_calls(self) -> list[Dict[str, Any]]:
        return [
            dict(event.payload)
            for event in self.events
            if event.type == TOOL_CALL
        ]

    def find_final(self) -> Optional[str]:
        for event in self.events:
            if event.type == FINAL:
                return str(event.payload.get("content") or "")
        return None
