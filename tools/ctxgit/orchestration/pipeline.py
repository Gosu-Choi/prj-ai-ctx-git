"""Deterministic Team pipeline state machine.

This is a 1:1 Python port of the oh-my-claudecode (OMC) team pipeline control
core, which ctxgit re-implements so the pipeline runs under ctxgit's own job
engine instead of OMC's Node runtime.

Ported from oh-my-claudecode (MIT License, Copyright (c) Yeachan Heo):
    src/hooks/team-pipeline/types.ts
    src/hooks/team-pipeline/state.ts
    src/hooks/team-pipeline/transitions.ts
See ORCHESTRATION_NOTICE.md for attribution.

The control core is intentionally small and pure: phases, the allowed-transition
table, entry guards, and the fix-loop bound. Persistence and agent execution live
elsewhere so this module stays trivially testable.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

TEAM_PIPELINE_SCHEMA_VERSION = 1

PHASE_PLAN = "team-plan"
PHASE_PRD = "team-prd"
PHASE_EXEC = "team-exec"
PHASE_VERIFY = "team-verify"
PHASE_FIX = "team-fix"
PHASE_COMPLETE = "complete"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"

#: Allowed phase transitions. Ported verbatim from transitions.ts `ALLOWED`.
ALLOWED: dict[str, list[str]] = {
    PHASE_PLAN: [PHASE_PRD],
    PHASE_PRD: [PHASE_EXEC],
    PHASE_EXEC: [PHASE_VERIFY],
    PHASE_VERIFY: [PHASE_FIX, PHASE_COMPLETE, PHASE_FAILED],
    PHASE_FIX: [PHASE_EXEC, PHASE_VERIFY, PHASE_COMPLETE, PHASE_FAILED],
    PHASE_COMPLETE: [],
    PHASE_FAILED: [],
    PHASE_CANCELLED: [PHASE_PLAN, PHASE_EXEC],  # only via resume
}

TERMINAL_PHASES = frozenset({PHASE_COMPLETE, PHASE_FAILED, PHASE_CANCELLED})

DEFAULT_MAX_ITERATIONS = 25
DEFAULT_MAX_FIX_ATTEMPTS = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class PhaseHistoryEntry:
    phase: str
    entered_at: str
    reason: Optional[str] = None


@dataclass
class Artifacts:
    plan_path: Optional[str] = None
    prd_path: Optional[str] = None
    verify_report_path: Optional[str] = None


@dataclass
class Execution:
    workers_total: int = 0
    workers_active: int = 0
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0


@dataclass
class FixLoop:
    attempt: int = 0
    max_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS
    last_failure_reason: Optional[str] = None


@dataclass
class Cancel:
    requested: bool = False
    requested_at: Optional[str] = None
    preserve_for_resume: bool = False


@dataclass
class TeamPipelineState:
    session_id: str
    project_path: str
    schema_version: int = TEAM_PIPELINE_SCHEMA_VERSION
    mode: str = "team"
    active: bool = True
    phase: str = PHASE_PLAN
    phase_history: list[PhaseHistoryEntry] = field(default_factory=list)
    iteration: int = 1
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    artifacts: Artifacts = field(default_factory=Artifacts)
    execution: Execution = field(default_factory=Execution)
    fix_loop: FixLoop = field(default_factory=FixLoop)
    cancel: Cancel = field(default_factory=Cancel)
    started_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None


@dataclass
class TransitionResult:
    ok: bool
    state: TeamPipelineState
    reason: Optional[str] = None


def init_team_pipeline_state(
    directory: str,
    session_id: str,
    *,
    project_path: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> TeamPipelineState:
    """Fresh pipeline state. Always starts at team-plan (mirrors initTeamPipelineState)."""
    stamp = now_iso()
    return TeamPipelineState(
        session_id=session_id,
        project_path=project_path if project_path is not None else directory,
        active=True,
        phase=PHASE_PLAN,
        phase_history=[PhaseHistoryEntry(phase=PHASE_PLAN, entered_at=stamp)],
        iteration=1,
        max_iterations=max_iterations if max_iterations is not None else DEFAULT_MAX_ITERATIONS,
        started_at=stamp,
        updated_at=stamp,
        completed_at=None,
    )


def is_terminal(state: TeamPipelineState) -> bool:
    return state.phase in TERMINAL_PHASES


def is_non_negative_finite_integer(value: Any) -> bool:
    """Mirror of transitions.ts `isNonNegativeFiniteInteger` (bools are not numbers here)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return math.isfinite(value) and value.is_integer() and value >= 0
    return False


def _is_allowed_transition(from_phase: str, to_phase: str) -> bool:
    return to_phase in ALLOWED.get(from_phase, [])


def has_required_artifacts_for_phase(state: TeamPipelineState, next_phase: str) -> Optional[str]:
    """Entry guards. Returns a failure reason, or None when the phase may be entered."""
    if next_phase == PHASE_EXEC:
        if not state.artifacts.plan_path and not state.artifacts.prd_path:
            return "team-exec requires plan_path or prd_path artifact"
        return None
    if next_phase == PHASE_VERIFY:
        if not is_non_negative_finite_integer(state.execution.tasks_total):
            return f"tasks_total must be a non-negative finite integer, got: {state.execution.tasks_total}"
        if not is_non_negative_finite_integer(state.execution.tasks_completed):
            return (
                "tasks_completed must be a non-negative finite integer, "
                f"got: {state.execution.tasks_completed}"
            )
        if state.execution.tasks_total <= 0:
            return "tasks_total must be > 0 for team-verify transition"
        if state.execution.tasks_completed < state.execution.tasks_total:
            return (
                f"tasks_completed ({state.execution.tasks_completed}) < "
                f"tasks_total ({state.execution.tasks_total})"
            )
        return None
    return None


def mark_team_phase(
    state: TeamPipelineState,
    next_phase: str,
    reason: Optional[str] = None,
) -> TransitionResult:
    """Enter `next_phase`, counting fix-loop retries and enforcing its bound.

    Mirrors state.ts `markTeamPhase`, including the fix-loop overflow that forces
    a terminal `failed` state.
    """
    # Idempotent, except team-fix -> team-fix, which is a retry increment.
    if state.phase == next_phase and next_phase != PHASE_FIX:
        return TransitionResult(ok=True, state=state)

    updated = copy.deepcopy(state)
    updated.phase = next_phase
    updated.phase_history = list(updated.phase_history) + [
        PhaseHistoryEntry(phase=next_phase, entered_at=now_iso(), reason=reason)
    ]

    if next_phase in TERMINAL_PHASES:
        updated.active = False
        updated.completed_at = now_iso()

    if next_phase == PHASE_FIX:
        updated.fix_loop.attempt += 1

    updated.updated_at = now_iso()

    if updated.fix_loop.attempt > updated.fix_loop.max_attempts:
        failed = copy.deepcopy(updated)
        failed.phase = PHASE_FAILED
        failed.active = False
        failed.completed_at = now_iso()
        failed.updated_at = now_iso()
        if failed.fix_loop.last_failure_reason is None:
            failed.fix_loop.last_failure_reason = "fix-loop-max-attempts-exceeded"
        failed.phase_history = list(failed.phase_history) + [
            PhaseHistoryEntry(
                phase=PHASE_FAILED,
                entered_at=now_iso(),
                reason="fix-loop-max-attempts-exceeded",
            )
        ]
        return TransitionResult(ok=False, state=failed, reason="Fix loop exceeded max_attempts")

    return TransitionResult(ok=True, state=updated)


def transition_team_phase(
    state: TeamPipelineState,
    next_phase: str,
    reason: Optional[str] = None,
) -> TransitionResult:
    """Guarded phase transition. Mirrors transitions.ts `transitionTeamPhase`."""
    if not _is_allowed_transition(state.phase, next_phase):
        return TransitionResult(
            ok=False,
            state=state,
            reason=f"Illegal transition: {state.phase} -> {next_phase}",
        )

    # Resuming from cancelled requires the preserve flag, and re-activates the run.
    if state.phase == PHASE_CANCELLED:
        if not state.cancel.preserve_for_resume:
            return TransitionResult(
                ok=False,
                state=state,
                reason="Cannot resume from cancelled: preserve_for_resume is not set",
            )
        resumed = copy.deepcopy(state)
        resumed.active = True
        resumed.completed_at = None
        return mark_team_phase(
            resumed,
            next_phase,
            reason if reason is not None else "resumed-from-cancelled",
        )

    guard_failure = has_required_artifacts_for_phase(state, next_phase)
    if guard_failure is not None:
        return TransitionResult(ok=False, state=state, reason=guard_failure)

    return mark_team_phase(state, next_phase, reason)


def request_team_cancel(
    state: TeamPipelineState,
    preserve_for_resume: bool = True,
) -> TeamPipelineState:
    """Cancel the run, optionally leaving it resumable. Mirrors `requestTeamCancel`."""
    stamp = now_iso()
    cancelled = copy.deepcopy(state)
    cancelled.cancel.requested = True
    cancelled.cancel.requested_at = stamp
    cancelled.cancel.preserve_for_resume = preserve_for_resume
    cancelled.phase = PHASE_CANCELLED
    cancelled.active = False
    cancelled.completed_at = stamp
    cancelled.updated_at = stamp
    cancelled.phase_history = list(cancelled.phase_history) + [
        PhaseHistoryEntry(phase=PHASE_CANCELLED, entered_at=stamp, reason="cancel-requested")
    ]
    return cancelled


def state_to_dict(state: TeamPipelineState) -> dict[str, Any]:
    return asdict(state)


def state_from_dict(payload: dict[str, Any]) -> TeamPipelineState:
    data = dict(payload or {})
    history = [
        PhaseHistoryEntry(
            phase=str(item.get("phase") or ""),
            entered_at=str(item.get("entered_at") or ""),
            reason=item.get("reason"),
        )
        for item in (data.get("phase_history") or [])
        if isinstance(item, dict)
    ]
    return TeamPipelineState(
        session_id=str(data.get("session_id") or ""),
        project_path=str(data.get("project_path") or ""),
        schema_version=int(data.get("schema_version") or TEAM_PIPELINE_SCHEMA_VERSION),
        mode=str(data.get("mode") or "team"),
        active=bool(data.get("active", True)),
        phase=str(data.get("phase") or PHASE_PLAN),
        phase_history=history,
        iteration=int(data.get("iteration") or 1),
        max_iterations=int(data.get("max_iterations") or DEFAULT_MAX_ITERATIONS),
        artifacts=Artifacts(**(data.get("artifacts") or {})),
        execution=Execution(**(data.get("execution") or {})),
        fix_loop=FixLoop(**(data.get("fix_loop") or {})),
        cancel=Cancel(**(data.get("cancel") or {})),
        started_at=str(data.get("started_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        completed_at=data.get("completed_at"),
    )
