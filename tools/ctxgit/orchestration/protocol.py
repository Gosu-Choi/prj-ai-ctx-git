"""Prompt fragments for the lead agent and for delegated workers.

Derived from oh-my-claudecode's `skills/team/SKILL.md` (MIT) — the stage routing
table, the worker preamble contract, and the handoff format. See
ORCHESTRATION_NOTICE.md.

Two distinct things live here:

* `LEAD_ORCHESTRATION_PROTOCOL` — injected when the subagent toggle is on and the
  lead agent orchestrates *adaptively* on its own (no deterministic pipeline).
* `worker_preamble()` / `handoff_template()` — used by the deterministic pipeline
  in `stages.py`, where ctxgit itself drives the stages.
"""

from __future__ import annotations

#: Roles the lead can delegate to, kept short for prompt budget.
ROLE_SUMMARY = (
    "planner (decomposes work into a task graph), explore (fast codebase search), "
    "analyst (requirements and acceptance criteria), architect (read-only design and "
    "debugging advice), executor (implements changes), debugger (root-cause analysis), "
    "test-engineer (test strategy and coverage), verifier (evidence-based completion "
    "checks), code-reviewer (severity-rated review), security-reviewer (OWASP and "
    "secrets), critic (final quality gate), writer / designer / document-specialist / "
    "scientist / tracer / code-simplifier / git-master / qa-tester"
)

LEAD_ORCHESTRATION_PROTOCOL = f"""

You can orchestrate a team of subagents via the Task tool to produce higher-quality
results. Orchestrate ADAPTIVELY — match effort to the task; never over-engineer a
trivial request. Available specialists: {ROLE_SUMMARY}.
Protocol:
1. Assess the task's complexity and whether it splits into independent parts. Trivial
   or purely conversational tasks: answer directly, no delegation.
2. Plan: for genuinely complex or ambiguous work, delegate to `planner` first to get a
   decomposition and an explicit acceptance bar.
3. Delegate in parallel: dispatch independent subtasks to the right specialist. Run at
   most 3-4 concurrently; give each a precise, self-contained brief with its acceptance
   bar. Workers do their task directly and never spawn further subagents.
4. Quality gate: before finalizing any substantial output, delegate a review to
   `verifier` (evidence-based completion check) and/or `critic` / `code-reviewer`. A
   completion claim needs fresh evidence, not "should work". If they return required
   changes, fix and re-check. Do NOT finalize until the review passes.
5. Synthesize the results into your own answer — you own the final result.
Delegate to amplify quality and parallelism, not for its own sake.
"""


def worker_preamble(role: str, brief: str, acceptance: str) -> str:
    """Contract injected into every pipeline-spawned worker.

    Mirrors OMC's worker preamble: work the assigned task directly, report, and stop.
    """
    return "\n".join(
        [
            f"You are the `{role}` worker on a ctxgit team pipeline stage.",
            "",
            "Contract:",
            "- WORK: do exactly the assigned task below, directly. Never spawn subagents.",
            "- SCOPE: stay inside the assigned task; do not start adjacent work.",
            "- REPORT: your final message is the deliverable handed back to the lead.",
            "",
            "Assigned task:",
            brief.strip(),
            "",
            "Acceptance bar:",
            acceptance.strip() or "Task is done and the result is reported with evidence.",
        ]
    )


def handoff_template(stage: str) -> str:
    """Lightweight stage handoff, read by the next stage. Mirrors OMC's handoff doc."""
    return "\n".join(
        [
            f"# Handoff: {stage}",
            "",
            "## Decided",
            "## Rejected",
            "## Risks",
            "## Files",
            "## Remaining",
        ]
    )
