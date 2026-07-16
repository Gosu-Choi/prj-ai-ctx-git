"""Record what the agents actually said to each other while producing one output.

The pipeline metadata says a run reached `complete` with verdict PASS; it does not
say which role was asked what, or what came back. That reasoning is the interesting
part of an orchestrated turn and it was being thrown away. This records it so a turn
can be replayed in the UI.

Kept deliberately small and serializable: one flat, ordered list of entries. Long
prompts and replies are excerpted — this is for reading, not for re-running.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

#: Entry kinds.
KIND_STAGE = "stage"  # ctxgit drove a pipeline stage by calling a role
KIND_DELEGATION = "delegation"  # a lead agent delegated to a subagent via Task
KIND_NOTE = "note"  # a plain progress note worth keeping

DEFAULT_EXCERPT = 4000


def excerpt(value: Any, limit: int = DEFAULT_EXCERPT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n\n… [{len(text) - limit} chars omitted] …\n\n{text[-tail:]}"


@dataclass
class TranscriptEntry:
    seq: int
    kind: str
    role: str = ""
    stage: str = ""
    label: str = ""
    model: str = ""
    started_at: str = ""
    duration_ms: int = 0
    prompt: str = ""
    reply: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Transcript:
    """An ordered record of one turn's orchestration."""

    turn_id: str = ""
    branch: str = ""
    mode: str = ""
    task: str = ""
    entries: list[TranscriptEntry] = field(default_factory=list)

    def record(
        self,
        kind: str,
        *,
        role: str = "",
        stage: str = "",
        label: str = "",
        model: str = "",
        started_at: str = "",
        duration_ms: int = 0,
        prompt: Any = "",
        reply: Any = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> TranscriptEntry:
        entry = TranscriptEntry(
            seq=len(self.entries) + 1,
            kind=kind,
            role=role,
            stage=stage,
            label=label,
            model=model,
            started_at=started_at,
            duration_ms=duration_ms,
            prompt=excerpt(prompt),
            reply=excerpt(reply),
            meta=meta or {},
        )
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "turnId": self.turn_id,
            "branch": self.branch,
            "mode": self.mode,
            "task": excerpt(self.task),
            "entries": [asdict(entry) for entry in self.entries],
        }


#: Separates delegations that the lead dispatched together in one message.
DELEGATION_SEPARATOR = " ;; "


def delegations_from_event(message: str) -> list[dict[str, str]]:
    """Pull every subagent delegation out of a progress line.

    The lead's delegations only exist as streamed events, so this is the one place a
    chat or sequence-room turn can capture them. A parallel batch arrives as several
    delegations in a single line, and all of them matter.
    """
    prefix = "Delegating to subagent: "
    if not message.startswith(prefix):
        return []
    results: list[dict[str, str]] = []
    for chunk in message[len(prefix):].split(DELEGATION_SEPARATOR):
        chunk = chunk.strip()
        if not chunk:
            continue
        role, _, description = chunk.partition(" · ")
        results.append({"role": role.strip(), "description": description.strip()})
    return results
