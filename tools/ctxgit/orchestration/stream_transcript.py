"""Reconstruct a turn's real subagent timeline from Claude Code's event stream.

`--output-format stream-json` emits, for every event, a timestamp and — for work
a subagent did — a `parent_tool_use_id` pointing back to the Task call that spawned
it. That is enough to answer the questions the old log could not: which subagent did
what, WHEN, and whether two of them actually overlapped.

This ingests the raw event dicts (not the formatted progress strings) and produces a
timeline: a lead track plus one lane per subagent, each with millisecond offsets so
the UI can lay them out on a shared time axis and show overlap.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

MAX_LABEL = 200
MAX_SUMMARY = 2000

_DELEGATION_TOOLS = {"Task", "Agent"}
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?")


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    match = _TS_RE.match(text)
    if not match:
        return None
    base, frac = match.group(1), match.group(2) or ""
    micros = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micros = int(digits)
    try:
        parsed = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(microsecond=micros, tzinfo=timezone.utc)


def _clip(value: Any, limit: int = MAX_LABEL) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_label(name: str, tool_input: Any) -> str:
    detail = ""
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "command", "pattern", "query", "url", "description"):
            if tool_input.get(key):
                detail = f" · {_clip(tool_input[key], 90)}"
                break
    return f"{name}{detail}"


class StreamTranscript:
    """Builds a subagent timeline from one Claude Code process's event stream."""

    def __init__(self) -> None:
        self._first_ts: Optional[datetime] = None
        self._last_ts: Optional[datetime] = None
        self._lead: list[dict[str, Any]] = []
        self._subagents: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    # -- ingest -------------------------------------------------------------
    def ingest(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type not in ("assistant", "user"):
            return
        ts = _parse_ts(event.get("timestamp"))
        if ts is not None:
            if self._first_ts is None or ts < self._first_ts:
                self._first_ts = ts
            if self._last_ts is None or ts > self._last_ts:
                self._last_ts = ts
        parent = event.get("parent_tool_use_id")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []

        if event_type == "assistant" and not parent:
            self._ingest_lead(ts, content, event.get("subagent_type"))
        elif parent:
            self._ingest_subagent(parent, ts, event_type, content, event.get("subagent_type"))

    def _ingest_lead(self, ts, content, _subagent_type) -> None:
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "tool_use":
                name = str(part.get("name") or "tool")
                if name == "StructuredOutput":
                    continue
                if name in _DELEGATION_TOOLS:
                    self._start_subagent(part, ts)
                    inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                    self._lead.append({
                        "ts": ts,
                        "kind": "delegate",
                        "label": str(inp.get("subagent_type") or "subagent"),
                        "ref": str(part.get("id") or ""),
                    })
                else:
                    self._lead.append({
                        "ts": ts, "kind": "tool", "label": _tool_label(name, part.get("input")),
                    })
            elif ptype == "text":
                text = _clip(part.get("text"), MAX_LABEL)
                if text:
                    self._lead.append({"ts": ts, "kind": "text", "label": text})

    def _start_subagent(self, part: dict, ts) -> None:
        sub_id = str(part.get("id") or "")
        if not sub_id or sub_id in self._subagents:
            return
        inp = part.get("input") if isinstance(part.get("input"), dict) else {}
        self._subagents[sub_id] = {
            "id": sub_id,
            "type": str(inp.get("subagent_type") or "subagent"),
            "brief": _clip(inp.get("description"), MAX_LABEL),
            "prompt": _clip(inp.get("prompt"), MAX_SUMMARY),
            "dispatched": ts,
            "started": None,
            "finished": None,
            "events": [],
            "summary": "",
        }
        self._order.append(sub_id)

    def _ensure_subagent(self, sub_id: str, subagent_type: Any) -> dict[str, Any]:
        agent = self._subagents.get(sub_id)
        if agent is None:
            agent = {
                "id": sub_id, "type": str(subagent_type or "subagent"), "brief": "",
                "prompt": "", "dispatched": None, "started": None, "finished": None,
                "events": [], "summary": "",
            }
            self._subagents[sub_id] = agent
            self._order.append(sub_id)
        elif subagent_type and agent["type"] == "subagent":
            agent["type"] = str(subagent_type)
        return agent

    def _ingest_subagent(self, parent, ts, event_type, content, subagent_type) -> None:
        agent = self._ensure_subagent(str(parent), subagent_type)
        if ts is not None:
            if agent["started"] is None or ts < agent["started"]:
                agent["started"] = ts
            if agent["finished"] is None or ts > agent["finished"]:
                agent["finished"] = ts
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "tool_use":
                agent["events"].append({
                    "ts": ts, "kind": "tool",
                    "label": _tool_label(str(part.get("name") or "tool"), part.get("input")),
                })
            elif ptype == "text":
                text = _clip(part.get("text"), MAX_LABEL)
                if text:
                    agent["events"].append({"ts": ts, "kind": "text", "label": text})
                    agent["summary"] = _clip(part.get("text"), MAX_SUMMARY)
            elif ptype == "tool_result":
                body = part.get("content")
                if isinstance(body, list):
                    body = " ".join(
                        str(item.get("text", "")) for item in body if isinstance(item, dict)
                    )
                agent["events"].append({"ts": ts, "kind": "result", "label": _clip(body, MAX_LABEL)})

    # -- output -------------------------------------------------------------
    @property
    def has_delegations(self) -> bool:
        return any(agent["events"] or agent["dispatched"] for agent in self._subagents.values())

    def _ms(self, ts) -> Optional[int]:
        if ts is None or self._first_ts is None:
            return None
        return int((ts - self._first_ts).total_seconds() * 1000)

    def timeline(self) -> dict[str, Any]:
        subagents = []
        for sub_id in self._order:
            agent = self._subagents[sub_id]
            start = agent["started"] or agent["dispatched"]
            end = agent["finished"] or start
            subagents.append({
                "id": agent["id"],
                "type": agent["type"],
                "brief": agent["brief"],
                "prompt": agent["prompt"],
                "dispatchedAt": self._ms(agent["dispatched"]),
                "startAt": self._ms(start),
                "endAt": self._ms(end),
                "durationMs": (
                    int((end - start).total_seconds() * 1000) if start and end else 0
                ),
                "summary": agent["summary"],
                "events": [
                    {"at": self._ms(item["ts"]), "kind": item["kind"], "label": item["label"]}
                    for item in agent["events"]
                ],
            })
        return {
            "totalMs": self._ms(self._last_ts) or 0,
            "lead": [
                {"at": self._ms(item["ts"]), "kind": item["kind"], "label": item["label"],
                 "ref": item.get("ref", "")}
                for item in self._lead
            ],
            "subagents": subagents,
        }
