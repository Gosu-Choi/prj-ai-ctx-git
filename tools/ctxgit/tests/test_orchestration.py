"""Tests for the orchestration package: the ported team pipeline and agent library."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402,F401  (must precede loading ctxgit: keeps tests out of the real ~/.ctxgit)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orchestration as orch  # noqa: E402


class TeamPipelineStateMachineTest(unittest.TestCase):
    def test_init_starts_at_plan_with_omc_defaults(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        self.assertEqual(state.phase, orch.PHASE_PLAN)
        self.assertTrue(state.active)
        self.assertEqual(state.iteration, 1)
        self.assertEqual(state.max_iterations, 25)
        self.assertEqual(state.fix_loop.max_attempts, 3)
        self.assertEqual([entry.phase for entry in state.phase_history], [orch.PHASE_PLAN])

    def test_illegal_transition_is_rejected(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        result = orch.transition_team_phase(state, orch.PHASE_VERIFY)
        self.assertFalse(result.ok)
        self.assertIn("Illegal transition", result.reason or "")
        self.assertEqual(result.state.phase, orch.PHASE_PLAN)

    def test_exec_requires_plan_or_prd_artifact(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        state = orch.transition_team_phase(state, orch.PHASE_PRD).state
        blocked = orch.transition_team_phase(state, orch.PHASE_EXEC)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.reason, "team-exec requires plan_path or prd_path artifact")

        state.artifacts.plan_path = "/proj/plan.md"
        allowed = orch.transition_team_phase(state, orch.PHASE_EXEC)
        self.assertTrue(allowed.ok)
        self.assertEqual(allowed.state.phase, orch.PHASE_EXEC)

    def test_verify_requires_all_tasks_completed(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        state = orch.transition_team_phase(state, orch.PHASE_PRD).state
        state.artifacts.prd_path = "/proj/prd.md"
        state = orch.transition_team_phase(state, orch.PHASE_EXEC).state

        zero = orch.transition_team_phase(state, orch.PHASE_VERIFY)
        self.assertFalse(zero.ok)
        self.assertIn("tasks_total must be > 0", zero.reason or "")

        state.execution.tasks_total = 2
        state.execution.tasks_completed = 1
        partial = orch.transition_team_phase(state, orch.PHASE_VERIFY)
        self.assertFalse(partial.ok)
        self.assertIn("tasks_completed (1) < tasks_total (2)", partial.reason or "")

        state.execution.tasks_completed = 2
        done = orch.transition_team_phase(state, orch.PHASE_VERIFY)
        self.assertTrue(done.ok)

    def test_fix_loop_is_bounded_and_fails_terminally(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        state = orch.transition_team_phase(state, orch.PHASE_PRD).state
        state.artifacts.prd_path = "/proj/prd.md"
        state = orch.transition_team_phase(state, orch.PHASE_EXEC).state
        state.execution.tasks_total = 1
        state.execution.tasks_completed = 1
        state = orch.transition_team_phase(state, orch.PHASE_VERIFY).state

        for attempt in range(1, 4):
            result = orch.transition_team_phase(state, orch.PHASE_FIX, f"round {attempt}")
            self.assertTrue(result.ok)
            self.assertEqual(result.state.fix_loop.attempt, attempt)
            state = result.state
            state = orch.transition_team_phase(state, orch.PHASE_VERIFY).state

        overflow = orch.transition_team_phase(state, orch.PHASE_FIX, "round 4")
        self.assertFalse(overflow.ok)
        self.assertEqual(overflow.state.phase, orch.PHASE_FAILED)
        self.assertFalse(overflow.state.active)
        self.assertEqual(
            overflow.state.fix_loop.last_failure_reason, "fix-loop-max-attempts-exceeded"
        )

    def test_same_phase_is_idempotent_except_fix(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        same = orch.mark_team_phase(state, orch.PHASE_PLAN)
        self.assertTrue(same.ok)
        self.assertEqual(len(same.state.phase_history), 1)

    def test_cancel_then_resume_requires_preserve_flag(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")

        resumable = orch.request_team_cancel(state, preserve_for_resume=True)
        self.assertEqual(resumable.phase, orch.PHASE_CANCELLED)
        self.assertFalse(resumable.active)
        resumed = orch.transition_team_phase(resumable, orch.PHASE_PLAN)
        self.assertTrue(resumed.ok)
        self.assertTrue(resumed.state.active)

        final = orch.request_team_cancel(state, preserve_for_resume=False)
        blocked = orch.transition_team_phase(final, orch.PHASE_PLAN)
        self.assertFalse(blocked.ok)
        self.assertIn("preserve_for_resume", blocked.reason or "")

    def test_non_negative_finite_integer_rejects_bools_and_floats(self) -> None:
        from orchestration.pipeline import is_non_negative_finite_integer as check

        self.assertTrue(check(0))
        self.assertTrue(check(3))
        self.assertTrue(check(3.0))
        self.assertFalse(check(True))
        self.assertFalse(check(-1))
        self.assertFalse(check(1.5))
        self.assertFalse(check(float("inf")))
        self.assertFalse(check("2"))

    def test_state_survives_json_round_trip(self) -> None:
        state = orch.init_team_pipeline_state("/proj", "sess")
        state.artifacts.plan_path = "/proj/plan.md"
        state.execution.tasks_total = 4
        restored = orch.state_from_dict(orch.state_to_dict(state))
        self.assertEqual(restored.phase, state.phase)
        self.assertEqual(restored.artifacts.plan_path, "/proj/plan.md")
        self.assertEqual(restored.execution.tasks_total, 4)
        self.assertEqual(len(restored.phase_history), len(state.phase_history))


class SubagentLibraryTest(unittest.TestCase):
    def test_vendored_roster_loads_with_tool_scoping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = orch.build_subagents(Path(tmp), writable=True)
            self.assertEqual(len(agents), 19)
            for role in ("planner", "executor", "verifier", "critic", "explore"):
                self.assertIn(role, agents)
            # verifier declares disallowedTools: Write, Edit
            self.assertNotIn("Write", agents["verifier"]["tools"])
            self.assertNotIn("Edit", agents["verifier"]["tools"])
            # executor is a writer role
            self.assertIn("Write", agents["executor"]["tools"])
            # model tier from frontmatter is preserved
            self.assertEqual(agents["verifier"]["model"], "sonnet")
            # subagents never get Task: workers do not spawn further subagents
            self.assertTrue(all("Task" not in entry["tools"] for entry in agents.values()))

    def test_read_only_sessions_withhold_write_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = orch.build_subagents(Path(tmp), writable=False)
            for entry in agents.values():
                self.assertNotIn("Write", entry["tools"])
                self.assertNotIn("Edit", entry["tools"])
                self.assertNotIn("Bash", entry["tools"])

    def test_ctxgit_own_agents_dir_is_not_treated_as_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "contexts" / "agents"
            legacy.mkdir(parents=True)
            (legacy / "research.md").write_text("# Research Agent\n\nPlan and verify.\n", encoding="utf-8")
            agents = orch.build_subagents(root, writable=True)
            self.assertNotIn("research", agents)
            self.assertEqual(len(agents), 19)

    def test_project_subagents_override_vendored_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overrides = root / "contexts" / "subagents"
            overrides.mkdir(parents=True)
            (overrides / "verifier.md").write_text(
                "---\nname: verifier\ndescription: Project verifier.\nmodel: opus\n---\nBe brutal.\n",
                encoding="utf-8",
            )
            (overrides / "house-style.md").write_text(
                "---\nname: house-style\ndescription: Checks house style.\n---\nCheck style rules.\n",
                encoding="utf-8",
            )
            agents = orch.build_subagents(root, writable=True)
            self.assertEqual(len(agents), 20)
            self.assertEqual(agents["verifier"]["description"], "Project verifier.")
            self.assertEqual(agents["verifier"]["model"], "opus")
            self.assertEqual(agents["verifier"]["prompt"], "Be brutal.")
            self.assertIn("house-style", agents)

    def test_protocol_only_points_at_roles_that_exist(self) -> None:
        # Pointing the lead at a role that is not in the roster just wastes a turn.
        # The protocol once told it to delegate to `researcher`, which does not exist.
        # Only backticked names are delegation targets; the prose around them is prose.
        import re

        with tempfile.TemporaryDirectory() as tmp:
            roster = set(orch.build_subagents(Path(tmp), writable=True))

        targets = set(re.findall(r"`([a-z][a-z-]+)`", orch.LEAD_ORCHESTRATION_PROTOCOL))
        self.assertTrue(targets, "protocol should name delegation targets")
        for role in targets:
            self.assertIn(role, roster, f"protocol points at a role that does not exist: {role}")

        # The roster summary the lead is shown must be real too.
        from orchestration.protocol import ROLE_SUMMARY

        for role in re.findall(r"([a-z][a-z-]+) \(", ROLE_SUMMARY):
            self.assertIn(role, roster, f"role summary names a role that does not exist: {role}")

    def test_stream_transcript_reconstructs_overlapping_subagents(self) -> None:
        st = orch.StreamTranscript()

        def ev(ts, obj):
            obj["timestamp"] = ts
            st.ingest(obj)

        ev("2026-01-01T00:00:00.000Z", {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Agent", "id": "AA",
             "input": {"subagent_type": "alpha", "description": "do alpha"}},
            {"type": "tool_use", "name": "Agent", "id": "BB",
             "input": {"subagent_type": "beta", "description": "do beta"}},
        ]}})
        ev("2026-01-01T00:00:01.000Z", {"type": "assistant", "parent_tool_use_id": "AA",
            "subagent_type": "alpha", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "sleep 5"}}]}})
        ev("2026-01-01T00:00:01.500Z", {"type": "assistant", "parent_tool_use_id": "BB",
            "subagent_type": "beta", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "sleep 5"}}]}})
        ev("2026-01-01T00:00:06.500Z", {"type": "assistant", "parent_tool_use_id": "AA",
            "subagent_type": "alpha", "message": {"content": [{"type": "text", "text": "alpha done"}]}})
        ev("2026-01-01T00:00:07.000Z", {"type": "assistant", "parent_tool_use_id": "BB",
            "subagent_type": "beta", "message": {"content": [{"type": "text", "text": "beta done"}]}})

        self.assertTrue(st.has_delegations)
        tl = st.timeline()
        self.assertEqual(len(tl["subagents"]), 2)
        a, b = tl["subagents"]
        self.assertEqual(a["type"], "alpha")
        self.assertEqual(a["startAt"], 1000)   # ms from the first event
        self.assertEqual(a["endAt"], 6500)
        self.assertEqual(a["summary"], "alpha done")
        # the two windows overlap -> genuinely concurrent
        overlap = min(a["endAt"], b["endAt"]) - max(a["startAt"], b["startAt"])
        self.assertGreater(overlap, 0)

    def test_stream_transcript_is_empty_without_delegations(self) -> None:
        st = orch.StreamTranscript()
        st.ingest({"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
                   "message": {"content": [{"type": "text", "text": "just answering"}]}})
        st.ingest({"type": "system", "subtype": "init"})
        self.assertFalse(st.has_delegations)
        self.assertEqual(st.timeline()["subagents"], [])

    def test_frontmatter_parser_keeps_body_with_dashes(self) -> None:
        meta, body = orch.parse_agent_markdown(
            "---\nname: t\ndescription: d\n---\n\nBody\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        )
        self.assertEqual(meta["name"], "t")
        self.assertIn("|---|---|", body)


def _plan_reply(tasks: list[dict]) -> orch.AgentReply:
    return orch.AgentReply(data={"summary": "plan", "tasks": tasks})


class TeamPipelineRunnerTest(unittest.TestCase):
    """The runner drives stages; the state machine decides when the run stops."""

    def _fake_call(self, verdicts: list[dict], calls: list[tuple[str, str]], tasks: list[dict]):
        verdict_iter = iter(verdicts)

        def call_agent(request: orch.AgentRequest) -> orch.AgentReply:
            calls.append((request.role, request.label))
            if request.label == "team-plan":
                return _plan_reply(tasks)
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["works"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(data=next(verdict_iter))
            return orch.AgentReply(text=f"{request.role} done")

        return call_agent

    def test_pipeline_completes_after_fix_rounds(self) -> None:
        tasks = [
            {"id": "t1", "title": "page", "brief": "b", "acceptance": "a", "role": "executor"},
            {"id": "t2", "title": "style", "brief": "b", "acceptance": "a", "role": "designer"},
        ]
        calls: list[tuple[str, str]] = []
        verdicts = [
            {"verdict": "FAIL", "evidence": "e", "requiredChanges": ["fix one"]},
            {"verdict": "PASS", "evidence": "fresh output", "requiredChanges": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            result = orch.run_team_pipeline(
                task="build it",
                workspace=workspace,
                session_id="s1",
                call_agent=self._fake_call(verdicts, calls, tasks),
                max_parallel=2,
            )
            self.assertEqual(result.state.phase, orch.PHASE_COMPLETE)
            self.assertFalse(result.state.active)
            self.assertEqual(result.state.fix_loop.attempt, 1)
            self.assertEqual(result.verify["verdict"], "PASS")
            phases = [entry.phase for entry in result.state.phase_history]
            self.assertEqual(
                phases,
                [
                    orch.PHASE_PLAN,
                    orch.PHASE_PRD,
                    orch.PHASE_EXEC,
                    orch.PHASE_VERIFY,
                    orch.PHASE_FIX,
                    orch.PHASE_EXEC,
                    orch.PHASE_VERIFY,
                    orch.PHASE_COMPLETE,
                ],
            )
            # artifacts and handoffs are on disk for the next stage / a resume
            self.assertTrue(Path(result.state.artifacts.plan_path).exists())
            self.assertTrue(Path(result.state.artifacts.prd_path).exists())
            self.assertTrue(Path(result.state.artifacts.verify_report_path).exists())
            self.assertTrue((workspace / ".team" / "handoffs" / "team-plan.md").exists())

    def test_planner_task_roles_are_routed_to_workers(self) -> None:
        tasks = [
            {"id": "t1", "title": "code", "brief": "b", "acceptance": "a", "role": "executor"},
            {"id": "t2", "title": "ui", "brief": "b", "acceptance": "a", "role": "designer"},
            {"id": "t3", "title": "tests", "brief": "b", "acceptance": "a", "role": "test-engineer"},
        ]
        calls: list[tuple[str, str]] = []
        verdicts = [{"verdict": "PASS", "evidence": "ok", "requiredChanges": []}]
        with tempfile.TemporaryDirectory() as tmp:
            orch.run_team_pipeline(
                task="build it",
                workspace=Path(tmp) / "ws",
                session_id="s2",
                call_agent=self._fake_call(verdicts, calls, tasks),
            )
        roles = {role for role, _ in calls}
        self.assertEqual({"planner", "analyst", "executor", "designer", "test-engineer", "verifier"}, roles)

    def test_unending_failures_stop_at_the_fix_loop_bound(self) -> None:
        tasks = [{"id": "t1", "title": "x", "brief": "b", "acceptance": "a", "role": "executor"}]
        calls: list[tuple[str, str]] = []
        verdicts = [{"verdict": "FAIL", "evidence": "e", "requiredChanges": ["again"]}] * 10
        with tempfile.TemporaryDirectory() as tmp:
            result = orch.run_team_pipeline(
                task="never passes",
                workspace=Path(tmp) / "ws",
                session_id="s3",
                call_agent=self._fake_call(verdicts, calls, tasks),
            )
        self.assertEqual(result.state.phase, orch.PHASE_FAILED)
        self.assertFalse(result.state.active)
        self.assertEqual(result.state.fix_loop.attempt, 4)  # 3 allowed, 4th trips the bound
        self.assertIn("Fix loop exceeded", result.stop_reason)

    def test_empty_plan_aborts_without_running_workers(self) -> None:
        # `failed` is reserved for "verification could not be satisfied" by the ported
        # transition table, so an abort before verify is a hard, non-resumable stop.
        calls: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            result = orch.run_team_pipeline(
                task="nothing to do",
                workspace=Path(tmp) / "ws",
                session_id="s4",
                call_agent=self._fake_call([], calls, []),
            )
        self.assertEqual(result.state.phase, orch.PHASE_CANCELLED)
        self.assertFalse(result.state.active)
        self.assertFalse(result.state.cancel.preserve_for_resume)
        self.assertEqual(result.stop_reason, "planner returned no tasks")
        self.assertEqual([role for role, _ in calls], ["planner"])

    def test_a_dead_worker_is_counted_failed_not_fatal(self) -> None:
        tasks = [
            {"id": "t1", "title": "ok", "brief": "b", "acceptance": "a", "role": "executor"},
            {"id": "t2", "title": "boom", "brief": "b", "acceptance": "a", "role": "executor"},
        ]

        def call_agent(request: orch.AgentRequest) -> orch.AgentReply:
            if request.label == "team-plan":
                return _plan_reply(tasks)
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["a"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(data={"verdict": "PASS", "evidence": "ok", "requiredChanges": []})
            if request.label == "team-exec:t2":
                raise RuntimeError("worker crashed")
            return orch.AgentReply(text="done")

        with tempfile.TemporaryDirectory() as tmp:
            result = orch.run_team_pipeline(
                task="build it",
                workspace=Path(tmp) / "ws",
                session_id="s5",
                call_agent=call_agent,
            )
        self.assertEqual(result.state.phase, orch.PHASE_COMPLETE)
        self.assertEqual(result.state.execution.tasks_failed, 1)
        self.assertEqual(result.state.execution.tasks_completed, 2)


if __name__ == "__main__":
    unittest.main()
