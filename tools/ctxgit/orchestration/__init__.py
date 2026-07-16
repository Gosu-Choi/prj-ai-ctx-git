"""ctxgit orchestration: subagent library and the deterministic team pipeline.

This package is deliberately independent of ctxgit.py. Anything that needs to talk
to a model is injected (see `stages.run_team_pipeline`'s `call_agent`), so the
control core stays pure and unit-testable.

Parts are derived from oh-my-claudecode (MIT) — see ORCHESTRATION_NOTICE.md.
"""

from __future__ import annotations

from .agents import (
    build_subagents,
    resolve_agent,
    build_subagents_json,
    load_project_agents,
    load_vendored_agents,
    parse_agent_markdown,
    subagent_tool_pool,
)
from .pipeline import (
    ALLOWED,
    DEFAULT_MAX_FIX_ATTEMPTS,
    DEFAULT_MAX_ITERATIONS,
    PHASE_CANCELLED,
    PHASE_COMPLETE,
    PHASE_EXEC,
    PHASE_FAILED,
    PHASE_FIX,
    PHASE_PLAN,
    PHASE_PRD,
    PHASE_VERIFY,
    TERMINAL_PHASES,
    TeamPipelineState,
    TransitionResult,
    has_required_artifacts_for_phase,
    init_team_pipeline_state,
    is_terminal,
    mark_team_phase,
    request_team_cancel,
    state_from_dict,
    state_to_dict,
    transition_team_phase,
)
from .protocol import (
    LEAD_ORCHESTRATION_PROTOCOL,
    WORKER_RUNTIME_OVERRIDE,
    handoff_template,
    worker_preamble,
)
from .transcript import Transcript, delegation_from_event
from .stages import (
    ASSIGNABLE_ROLES,
    DEFAULT_MAX_PARALLEL,
    STAGE_ROUTING,
    AgentReply,
    AgentRequest,
    PipelineResult,
    run_team_pipeline,
)

__all__ = [
    "ALLOWED",
    "ASSIGNABLE_ROLES",
    "DEFAULT_MAX_PARALLEL",
    "STAGE_ROUTING",
    "AgentReply",
    "AgentRequest",
    "PipelineResult",
    "run_team_pipeline",
    "Transcript",
    "delegation_from_event",
    "DEFAULT_MAX_FIX_ATTEMPTS",
    "DEFAULT_MAX_ITERATIONS",
    "LEAD_ORCHESTRATION_PROTOCOL",
    "WORKER_RUNTIME_OVERRIDE",
    "PHASE_CANCELLED",
    "PHASE_COMPLETE",
    "PHASE_EXEC",
    "PHASE_FAILED",
    "PHASE_FIX",
    "PHASE_PLAN",
    "PHASE_PRD",
    "PHASE_VERIFY",
    "TERMINAL_PHASES",
    "TeamPipelineState",
    "TransitionResult",
    "build_subagents",
    "resolve_agent",
    "build_subagents_json",
    "handoff_template",
    "has_required_artifacts_for_phase",
    "init_team_pipeline_state",
    "is_terminal",
    "load_project_agents",
    "load_vendored_agents",
    "mark_team_phase",
    "parse_agent_markdown",
    "request_team_cancel",
    "state_from_dict",
    "state_to_dict",
    "subagent_tool_pool",
    "transition_team_phase",
    "worker_preamble",
]
