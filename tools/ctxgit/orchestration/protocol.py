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


#: Appended to every pipeline worker's system prompt.
#:
#: The vendored role prompts were written for OMC's runtime, so they tell agents to
#: save plans under `.omc/plans/`, to interview a user, and to use tools ctxgit does
#: not grant. Left alone a planner burns its turn trying to persist a plan file
#: outside the workspace and returns an empty task list, which aborts the run. The
#: prompts stay pristine; this override reconciles them with ctxgit at call time.
WORKER_RUNTIME_OVERRIDE = (
    "You are running inside ctxgit as a team pipeline worker.\n"
    "- Your role prompt was written for a different runtime. Ignore any instruction in it "
    "to save plans, PRDs, or reports under `.omc/` paths, to interview a user, or to use "
    "tools you have not been granted. There is no interactive user here, and ctxgit "
    "persists every artifact for you.\n"
    "- Work only inside the current working directory. Never read or write outside it, and "
    "never push, publish, or deploy.\n"
    "- When a structured output schema is required, it REPLACES your role prompt's "
    "Output_Format and Final_Response_Contract sections. The structured output is then your "
    "ONLY deliverable: put the substance in its fields, never in prose or a fenced code "
    "block. A field that should hold a list must hold that list — do not describe the list "
    "in another field instead."
)


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
