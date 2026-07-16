"""Stage runners that drive the team pipeline deterministically.

ctxgit owns the control flow here: it advances the state machine in `pipeline.py`
and calls one agent per stage, instead of asking a lead model to remember a
procedure. Stage routing, the worker contract, and the handoff format follow
oh-my-claudecode's `skills/team/SKILL.md` (MIT) — see ORCHESTRATION_NOTICE.md.

Everything that talks to a model is injected as `call_agent`, so this module has no
dependency on ctxgit.py and can be unit-tested with a fake.

Flow (bounded by the state machine, not by this code):

    team-plan -> team-prd -> team-exec -> team-verify -+-> complete
                                ^                      |
                                +---- team-fix <-------+
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .pipeline import (
    PHASE_COMPLETE,
    PHASE_EXEC,
    PHASE_FAILED,
    PHASE_FIX,
    PHASE_PLAN,
    PHASE_PRD,
    PHASE_VERIFY,
    TeamPipelineState,
    init_team_pipeline_state,
    request_team_cancel,
    transition_team_phase,
)
from .protocol import handoff_template, worker_preamble
from .transcript import KIND_STAGE, Transcript

#: Which specialists each stage draws on. Ported from SKILL.md's stage routing table.
STAGE_ROUTING: dict[str, dict[str, list[str]]] = {
    PHASE_PLAN: {"required": ["planner"], "optional": ["explore", "analyst", "architect"]},
    PHASE_PRD: {"required": ["analyst"], "optional": ["critic"]},
    PHASE_EXEC: {
        "required": ["executor"],
        "optional": ["debugger", "designer", "writer", "test-engineer"],
    },
    PHASE_VERIFY: {
        "required": ["verifier"],
        "optional": ["test-engineer", "security-reviewer", "code-reviewer"],
    },
    PHASE_FIX: {"required": ["executor"], "optional": ["debugger"]},
}

#: Roles a planner may assign to a task. Keeps the plan routable.
ASSIGNABLE_ROLES = ["executor", "debugger", "designer", "writer", "test-engineer"]

DEFAULT_MAX_PARALLEL = 4

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "tasks"],
    "properties": {
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            # A plan with no tasks aborts the run, so make the schema reject it rather
            # than relying on the planner's goodwill.
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title", "brief", "acceptance", "role"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "brief": {"type": "string"},
                    "acceptance": {"type": "string"},
                    "role": {"type": "string", "enum": ASSIGNABLE_ROLES},
                },
            },
        },
    },
}

PRD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["acceptanceCriteria", "outOfScope"],
    "properties": {
        "acceptanceCriteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "outOfScope": {"type": "array", "items": {"type": "string"}},
    },
}

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "evidence", "requiredChanges"],
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL", "INCOMPLETE"]},
        "evidence": {"type": "string"},
        "requiredChanges": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass
class AgentRequest:
    role: str
    prompt: str
    writable: bool
    schema: Optional[dict[str, Any]] = None
    label: str = ""


@dataclass
class AgentReply:
    text: str = ""
    data: Optional[dict[str, Any]] = None


CallAgent = Callable[[AgentRequest], AgentReply]
Progress = Callable[[str], None]


@dataclass
class PipelineResult:
    state: TeamPipelineState
    summary: str = ""
    tasks: list[dict[str, Any]] = field(default_factory=list)
    verify: Optional[dict[str, Any]] = None
    stop_reason: str = ""


def _emit(progress: Optional[Progress], message: str) -> None:
    if progress:
        progress(message)


def _team_dir(workspace: Path) -> Path:
    return workspace / ".team"


def _write_artifact(workspace: Path, relative: str, text: str) -> str:
    path = _team_dir(workspace) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_handoff(workspace: Path, stage: str, body: str) -> str:
    """Persist a stage handoff the next stage reads. Mirrors OMC's handoff docs."""
    content = body.strip() or handoff_template(stage)
    return _write_artifact(workspace, f"handoffs/{stage}.md", content + "\n")


def read_handoffs(workspace: Path) -> str:
    directory = _team_dir(workspace) / "handoffs"
    if not directory.is_dir():
        return ""
    chunks = []
    for path in sorted(directory.glob("*.md")):
        try:
            chunks.append(path.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _context_block(task: str, workspace: Path) -> str:
    handoffs = read_handoffs(workspace)
    parts = [f"Goal:\n{task.strip()}"]
    if handoffs:
        parts.append(f"Handoffs from earlier stages:\n{handoffs}")
    return "\n\n".join(parts)


def run_plan_stage(
    state: TeamPipelineState,
    *,
    task: str,
    workspace: Path,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
) -> tuple[TeamPipelineState, list[dict[str, Any]], str]:
    _emit(progress, "team-plan: planner is decomposing the goal")
    reply = call_agent(
        AgentRequest(
            role="planner",
            writable=False,
            schema=PLAN_SCHEMA,
            label="team-plan",
            prompt="\n\n".join(
                [
                    _context_block(task, workspace),
                    "Decompose this goal into independent tasks that separate workers can do in "
                    "parallel. Assign each task the most suitable role from: "
                    + ", ".join(ASSIGNABLE_ROLES)
                    + ". Every task needs a concrete acceptance bar. Do not implement anything, "
                    "and do not try to save a plan file — ctxgit writes the plan from your "
                    "structured output. The `tasks` array IS your deliverable: returning it "
                    "empty aborts the run.",
                ]
            ),
        )
    )
    data = reply.data or {}
    tasks = [item for item in (data.get("tasks") or []) if isinstance(item, dict)]
    summary = str(data.get("summary") or reply.text or "").strip()

    plan_lines = [f"# Plan", "", summary, ""]
    for item in tasks:
        plan_lines.extend(
            [
                f"## {item.get('id')} — {item.get('title')}",
                f"- role: {item.get('role')}",
                f"- brief: {item.get('brief')}",
                f"- acceptance: {item.get('acceptance')}",
                "",
            ]
        )
    plan_path = _write_artifact(workspace, "plan.md", "\n".join(plan_lines))

    state.artifacts.plan_path = plan_path
    state.execution.tasks_total = len(tasks)
    state.execution.tasks_completed = 0
    state.execution.tasks_failed = 0
    write_handoff(
        workspace,
        PHASE_PLAN,
        f"# Handoff: {PHASE_PLAN}\n\n## Decided\n{summary}\n\n## Remaining\n{len(tasks)} task(s) planned.",
    )
    _emit(progress, f"team-plan: {len(tasks)} task(s) planned")
    return state, tasks, summary


def run_prd_stage(
    state: TeamPipelineState,
    *,
    task: str,
    workspace: Path,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
) -> TeamPipelineState:
    _emit(progress, "team-prd: analyst is fixing acceptance criteria")
    reply = call_agent(
        AgentRequest(
            role="analyst",
            writable=False,
            schema=PRD_SCHEMA,
            label="team-prd",
            prompt="\n\n".join(
                [
                    _context_block(task, workspace),
                    "State the explicit acceptance criteria this work must meet, and what is out of "
                    "scope. Be concrete and testable. Do not implement anything.",
                ]
            ),
        )
    )
    data = reply.data or {}
    criteria = [str(item) for item in (data.get("acceptanceCriteria") or [])]
    out_of_scope = [str(item) for item in (data.get("outOfScope") or [])]

    prd_lines = ["# Acceptance criteria", ""]
    prd_lines += [f"- {item}" for item in criteria] or ["- (none stated)"]
    prd_lines += ["", "# Out of scope", ""]
    prd_lines += [f"- {item}" for item in out_of_scope] or ["- (none stated)"]
    state.artifacts.prd_path = _write_artifact(workspace, "prd.md", "\n".join(prd_lines))

    write_handoff(
        workspace,
        PHASE_PRD,
        "# Handoff: team-prd\n\n## Decided\n"
        + "\n".join(f"- {item}" for item in criteria)
        + "\n\n## Rejected\n"
        + "\n".join(f"- {item}" for item in out_of_scope),
    )
    _emit(progress, f"team-prd: {len(criteria)} acceptance criterion(s)")
    return state


def run_exec_stage(
    state: TeamPipelineState,
    *,
    task: str,
    tasks: list[dict[str, Any]],
    workspace: Path,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
) -> TeamPipelineState:
    """Run every task through its assigned worker, up to `max_parallel` at a time."""
    if not tasks:
        return state

    context = _context_block(task, workspace)
    state.execution.workers_total = len(tasks)
    state.execution.tasks_completed = 0
    state.execution.tasks_failed = 0
    _emit(progress, f"team-exec: dispatching {len(tasks)} worker(s), {max_parallel} at a time")

    def run_one(item: dict[str, Any]) -> bool:
        role = str(item.get("role") or "executor")
        if role not in ASSIGNABLE_ROLES:
            role = "executor"
        brief = f"{item.get('title')}\n\n{item.get('brief')}"
        prompt = "\n\n".join(
            [
                context,
                worker_preamble(role, brief, str(item.get("acceptance") or "")),
            ]
        )
        try:
            reply = call_agent(
                AgentRequest(
                    role=role,
                    prompt=prompt,
                    writable=True,
                    label=f"team-exec:{item.get('id')}",
                )
            )
        except Exception:  # noqa: BLE001 - a dead worker must not kill the pipeline
            return False
        return bool((reply.text or "").strip())

    workers = max(1, min(int(max_parallel), len(tasks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(run_one, tasks))

    state.execution.tasks_completed = len(results)
    state.execution.tasks_failed = sum(1 for ok in results if not ok)
    state.execution.workers_active = 0
    _emit(
        progress,
        f"team-exec: {state.execution.tasks_completed}/{state.execution.tasks_total} task(s) done"
        + (f", {state.execution.tasks_failed} failed" if state.execution.tasks_failed else ""),
    )
    return state


def run_verify_stage(
    state: TeamPipelineState,
    *,
    task: str,
    workspace: Path,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
) -> tuple[TeamPipelineState, dict[str, Any]]:
    _emit(progress, "team-verify: verifier is checking against acceptance criteria")
    reply = call_agent(
        AgentRequest(
            role="verifier",
            writable=True,  # verification needs Bash to actually run things
            schema=VERIFY_SCHEMA,
            label="team-verify",
            prompt="\n\n".join(
                [
                    _context_block(task, workspace),
                    "Verify the work against the acceptance criteria using FRESH evidence you gather "
                    "yourself (run it, read it, recompute it). Return PASS only when every criterion "
                    "is backed by evidence; otherwise FAIL with the concrete required changes.",
                ]
            ),
        )
    )
    data = reply.data or {}
    verdict = str(data.get("verdict") or "INCOMPLETE").upper()
    required = [str(item) for item in (data.get("requiredChanges") or [])]
    evidence = str(data.get("evidence") or reply.text or "").strip()

    report = "\n".join(
        [
            "# Verification report",
            "",
            f"- verdict: {verdict}",
            "",
            "## Evidence",
            evidence or "(none provided)",
            "",
            "## Required changes",
            *([f"- {item}" for item in required] or ["- (none)"]),
        ]
    )
    state.artifacts.verify_report_path = _write_artifact(workspace, "verify-report.md", report)
    write_handoff(
        workspace,
        PHASE_VERIFY,
        f"# Handoff: team-verify\n\n## Decided\nverdict: {verdict}\n\n## Remaining\n"
        + ("\n".join(f"- {item}" for item in required) or "- (none)"),
    )
    _emit(progress, f"team-verify: {verdict}" + (f", {len(required)} required change(s)" if required else ""))
    return state, {"verdict": verdict, "requiredChanges": required, "evidence": evidence}


def run_fix_stage(
    state: TeamPipelineState,
    *,
    task: str,
    required_changes: list[str],
    workspace: Path,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
) -> tuple[TeamPipelineState, list[dict[str, Any]]]:
    """Turn the verifier's required changes into the next exec pass's task list."""
    _emit(progress, f"team-fix: {len(required_changes)} required change(s) queued")
    tasks = [
        {
            "id": f"fix-{state.fix_loop.attempt}-{index + 1}",
            "title": f"Fix: {change[:60]}",
            "brief": change,
            "acceptance": "The required change is implemented and verifiable.",
            "role": "executor",
        }
        for index, change in enumerate(required_changes)
    ]
    state.execution.tasks_total = len(tasks)
    state.execution.tasks_completed = 0
    write_handoff(
        workspace,
        PHASE_FIX,
        "# Handoff: team-fix\n\n## Remaining\n"
        + "\n".join(f"- {change}" for change in required_changes),
    )
    return state, tasks


def _recording(call_agent: CallAgent, transcript: Optional[Transcript]) -> CallAgent:
    """Wrap call_agent so each stage call lands in the transcript."""
    if transcript is None:
        return call_agent

    def recorded(request: AgentRequest) -> AgentReply:
        started = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        clock = time.monotonic()
        try:
            reply = call_agent(request)
        except Exception as exc:  # noqa: BLE001 - a failed worker is part of the story
            transcript.record(
                KIND_STAGE,
                role=request.role,
                stage=(request.label or "").split(":")[0],
                label=request.label,
                started_at=started,
                duration_ms=int((time.monotonic() - clock) * 1000),
                prompt=request.prompt,
                reply=f"[worker failed] {exc}",
                meta={"writable": request.writable, "failed": True},
            )
            raise
        transcript.record(
            KIND_STAGE,
            role=request.role,
            stage=(request.label or "").split(":")[0],
            label=request.label,
            started_at=started,
            duration_ms=int((time.monotonic() - clock) * 1000),
            prompt=request.prompt,
            reply=reply.text or (json.dumps(reply.data, ensure_ascii=False, indent=2) if reply.data else ""),
            meta={"writable": request.writable, "structured": reply.data is not None},
        )
        return reply

    return recorded


def run_team_pipeline(
    *,
    task: str,
    workspace: Path,
    session_id: str,
    call_agent: CallAgent,
    progress: Optional[Progress] = None,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    max_iterations: Optional[int] = None,
    transcript: Optional[Transcript] = None,
) -> PipelineResult:
    """Drive plan -> prd -> exec -> verify -> (fix -> exec -> verify)* to a terminal phase.

    Phase changes go through `transition_team_phase`, so the guards and the fix-loop
    bound decide when the run stops — this function never invents its own exit.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    call_agent = _recording(call_agent, transcript)
    state = init_team_pipeline_state(
        str(workspace), session_id, project_path=str(workspace), max_iterations=max_iterations
    )
    result = PipelineResult(state=state)

    def abort(reason: str) -> PipelineResult:
        """Stop a run that cannot proceed.

        The ported transition table only reaches `failed` from team-verify/team-fix —
        that is reserved for "verification could not be satisfied". An abort before
        that (no plan, a guard rejection) is a hard stop instead: terminal, inactive,
        and not resumable.
        """
        result.state = request_team_cancel(result.state, preserve_for_resume=False)
        result.stop_reason = reason
        _emit(progress, f"pipeline aborted: {reason}")
        return result

    # team-plan
    state, tasks, summary = run_plan_stage(
        state, task=task, workspace=workspace, call_agent=call_agent, progress=progress
    )
    result.state, result.tasks, result.summary = state, tasks, summary
    if not tasks:
        return abort("planner returned no tasks")

    # team-prd
    moved = transition_team_phase(result.state, PHASE_PRD, "plan ready")
    if not moved.ok:
        return abort(moved.reason or "cannot enter team-prd")
    result.state = run_prd_stage(
        moved.state, task=task, workspace=workspace, call_agent=call_agent, progress=progress
    )

    pending_tasks = tasks
    while True:
        # team-exec
        moved = transition_team_phase(result.state, PHASE_EXEC, "work queued")
        if not moved.ok:
            return abort(moved.reason or "cannot enter team-exec")
        result.state = run_exec_stage(
            moved.state,
            task=task,
            tasks=pending_tasks,
            workspace=workspace,
            call_agent=call_agent,
            progress=progress,
            max_parallel=max_parallel,
        )

        # team-verify
        moved = transition_team_phase(result.state, PHASE_VERIFY, "exec pass finished")
        if not moved.ok:
            return abort(moved.reason or "cannot enter team-verify")
        result.state, verify = run_verify_stage(
            moved.state, task=task, workspace=workspace, call_agent=call_agent, progress=progress
        )
        result.verify = verify

        if verify["verdict"] == "PASS":
            moved = transition_team_phase(result.state, PHASE_COMPLETE, "verification passed")
            result.state = moved.state
            result.stop_reason = "verification passed"
            _emit(progress, "pipeline complete: verification passed")
            return result

        required = verify["requiredChanges"] or ["Address the verifier's findings."]

        # team-fix — the state machine counts the attempt and terminates the run
        # once it exceeds max_attempts.
        moved = transition_team_phase(result.state, PHASE_FIX, "verification failed")
        result.state = moved.state
        if not moved.ok:
            result.stop_reason = moved.reason or "fix loop exhausted"
            _emit(progress, f"pipeline failed: {result.stop_reason}")
            return result

        result.state, pending_tasks = run_fix_stage(
            result.state,
            task=task,
            required_changes=required,
            workspace=workspace,
            call_agent=call_agent,
            progress=progress,
        )
