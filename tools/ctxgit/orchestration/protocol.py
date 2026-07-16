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

You lead a team of subagents and can dispatch work to them with the Task tool.
Available specialists: {ROLE_SUMMARY}.

WHEN TO DELEGATE — apply this test, do not go by feel:
- The request asks for 2 or more independent deliverables (separate files, separate
  questions, separate checks, separate areas to investigate)? Dispatch them to workers
  IN PARALLEL in a single batch. Doing independent parts yourself, one after another,
  is the failure this team exists to prevent — it is slower and no better.
- The work needs investigation you would otherwise do serially (reading several
  sources, several files, several angles)? Fan that out to `explore` / `scientist` /
  `document-specialist`.
- Substantial output that a reviewer could catch problems in? Send it to `verifier`
  (evidence-based check) or `critic`/`code-reviewer` before you finalize.
- It is a single small edit, a lookup, or a conversational answer? Do it yourself.
  Delegating one trivial thing is pure overhead.

HOW:
1. Split the request into independent units of work. If the split is unclear or the
   work is large, ask `planner` first.
2. Dispatch up to 3-4 workers concurrently. Give each a precise, self-contained brief
   and its acceptance bar — a worker sees none of the others' work.
3. Workers do their task directly and never spawn further subagents.
4. Quality gate: a completion claim needs fresh evidence, not "should work". If the
   reviewer returns required changes, fix them and re-check before finalizing.
5. Synthesize their results into your own answer — you own the final result.
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
