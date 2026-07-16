"""Tests for the orchestration package: the ported team pipeline and agent library."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_frontmatter_parser_keeps_body_with_dashes(self) -> None:
        meta, body = orch.parse_agent_markdown(
            "---\nname: t\ndescription: d\n---\n\nBody\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        )
        self.assertEqual(meta["name"], "t")
        self.assertIn("|---|---|", body)


if __name__ == "__main__":
    unittest.main()
