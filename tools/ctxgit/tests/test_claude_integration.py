"""Tests for the Claude integration layer in ctxgit.py.

Covers the seams between ctxgit and the orchestration package: how the claude
command is built, how streamed output is parsed, the team-pipeline turn, sequence
interjection, and revealing a branch directory. The model is always faked — these
assert our own wiring, not Claude's behavior.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
SPEC = importlib.util.spec_from_file_location("ctxgit", MODULE_PATH)
assert SPEC and SPEC.loader
ctxgit = importlib.util.module_from_spec(SPEC)
sys.modules["ctxgit"] = ctxgit
SPEC.loader.exec_module(ctxgit)

import orchestration as orch  # noqa: E402  (ctxgit.py puts tools/ctxgit on sys.path)


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def structured_result(payload: dict) -> str:
    return json.dumps({"type": "result", "subtype": "success", "structured_output": payload})


class ClaudeCommandTest(unittest.TestCase):
    """What we actually hand to the claude CLI."""

    def _capture_chat_command(self, root: Path, store, branch: str) -> list[str]:
        seen: list[list[str]] = []
        original = ctxgit.subprocess.run

        def fake_run(cmd, **_kwargs):
            if "auth" in cmd and "status" in cmd:
                return FakeCompleted(stdout="Logged in")
            seen.append(cmd)
            return FakeCompleted(
                stdout=structured_result(
                    {"assistant": "ok", "artifacts": [], "approvalRequests": []}
                )
            )

        ctxgit.subprocess.run = fake_run
        try:
            ctxgit.call_claude_chat(root, store, branch, "do the thing")
        finally:
            ctxgit.subprocess.run = original
        return seen[0]

    def _project(self, tmp: str, **provider):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        ctxgit.write_provider_config(root, {"provider": "claude", **provider})
        return root, store

    def test_chat_streams_and_forces_strict_schema_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertIn("--output-format", cmd)
            self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
            self.assertIn("--verbose", cmd)
            self.assertIn("--json-schema", cmd)

    def test_orchestration_mode_gates_task_agents_and_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp, orchestration="omc")
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertIn("Task", cmd[cmd.index("--tools") + 1])
            self.assertIn("--agents", cmd)
            agents = json.loads(cmd[cmd.index("--agents") + 1])
            self.assertEqual(len(agents), 19)
            self.assertIn("planner", agents)
            self.assertIn(
                orch.LEAD_ORCHESTRATION_PROTOCOL.strip(),
                cmd[cmd.index("--append-system-prompt") + 1],
            )

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp, orchestration="legacy")
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertNotIn("Task", cmd[cmd.index("--tools") + 1])
            self.assertNotIn("--agents", cmd)
            self.assertNotIn(
                orch.LEAD_ORCHESTRATION_PROTOCOL.strip(),
                cmd[cmd.index("--append-system-prompt") + 1],
            )

    def _run_stage_agent(self, root: Path, seen: list, stdout: str, **request_kwargs):
        original = ctxgit.subprocess.run

        def fake_run(cmd, **_kwargs):
            if "auth" in cmd and "status" in cmd:
                return FakeCompleted(stdout="Logged in")
            seen.append(cmd)
            return FakeCompleted(stdout=stdout)

        ctxgit.subprocess.run = fake_run
        try:
            return ctxgit.call_claude_agent(root, orch.AgentRequest(**request_kwargs), cwd=root)
        finally:
            ctxgit.subprocess.run = original

    def test_stage_injects_the_role_prompt_instead_of_pinning_an_agent(self) -> None:
        # Regression guard: `--agent` makes Claude Code silently ignore --json-schema,
        # which left the planner returning prose and no tasks. The role has to be
        # injected as a system prompt instead.
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            seen: list[list[str]] = []
            reply = self._run_stage_agent(
                root,
                seen,
                json.dumps(
                    {"type": "result", "result": "raw text", "structured_output": {"verdict": "PASS"}}
                ),
                role="verifier",
                prompt="check it",
                writable=True,
                schema={"type": "object"},
                label="team-verify",
            )

            cmd = seen[0]
            self.assertNotIn("--agent", cmd)
            self.assertIn("--json-schema", cmd)
            system_prompt = cmd[cmd.index("--append-system-prompt") + 1]
            self.assertIn("You are Verifier", system_prompt)
            self.assertIn("ctxgit", system_prompt)
            # the role's tier from the agent library picks the model
            self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
            # verifier declares disallowedTools: Write, Edit — and no worker re-delegates
            self.assertNotIn("Task", cmd[cmd.index("--tools") + 1])
            self.assertNotIn("Write", cmd[cmd.index("--tools") + 1])
            self.assertEqual(reply.data, {"verdict": "PASS"})
            self.assertEqual(reply.text, "raw text")

    def test_missing_structured_output_is_an_error_not_an_empty_result(self) -> None:
        # The silent version of this cost a whole pipeline run: no structured output
        # became "0 tasks planned" and an aborted pipeline.
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            with self.assertRaises(RuntimeError) as caught:
                self._run_stage_agent(
                    root,
                    [],
                    json.dumps({"type": "result", "subtype": "success", "result": "prose only"}),
                    role="planner",
                    prompt="plan it",
                    writable=False,
                    schema={"type": "object"},
                    label="team-plan",
                )
            self.assertIn("no structured output", str(caught.exception))

    def test_unknown_role_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            with self.assertRaises(RuntimeError):
                self._run_stage_agent(
                    root, [], "", role="nope", prompt="p", writable=True, label="x"
                )

    def test_stage_agent_raises_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            original = ctxgit.subprocess.run

            def fake_run(cmd, **_kwargs):
                if "auth" in cmd and "status" in cmd:
                    return FakeCompleted(stdout="Logged in")
                return FakeCompleted(stderr="boom", returncode=1)

            ctxgit.subprocess.run = fake_run
            try:
                with self.assertRaises(RuntimeError):
                    ctxgit.call_claude_agent(
                        root,
                        orch.AgentRequest(role="executor", prompt="p", writable=True),
                        cwd=root,
                    )
            finally:
                ctxgit.subprocess.run = original


class ClaudeStreamParsingTest(unittest.TestCase):
    """stream-json is JSONL; the final `result` event carries the payload."""

    def test_final_result_is_taken_from_a_jsonl_stream(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init"}),
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}),
                json.dumps({"type": "result", "structured_output": {"assistant": "final"}}),
            ]
        )
        payload = ctxgit.claude_final_result_payload(raw)
        self.assertEqual(payload["structured_output"], {"assistant": "final"})

    def test_single_object_output_still_parses(self) -> None:
        raw = json.dumps({"type": "result", "structured_output": {"assistant": "final"}})
        self.assertEqual(ctxgit.claude_final_result_payload(raw)["structured_output"], {"assistant": "final"})

    def test_parse_claude_result_extracts_sequence_evaluation_from_stream(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "assistant", "message": {"content": []}}),
                json.dumps(
                    {
                        "type": "result",
                        "structured_output": {
                            "assistant": "body",
                            "artifacts": [],
                            "approvalRequests": [],
                            "sequenceEvaluation": {"decision": "continue"},
                        },
                    }
                ),
            ]
        )
        parsed = ctxgit.parse_claude_result(raw)
        self.assertEqual(parsed["assistant"], "body")
        self.assertEqual(parsed["sequenceEvaluation"], {"decision": "continue"})

    def test_non_json_output_falls_back_to_raw_text(self) -> None:
        parsed = ctxgit.parse_claude_result("just prose, not json")
        self.assertEqual(parsed["assistant"], "just prose, not json")
        self.assertEqual(parsed["artifacts"], [])

    def test_stream_progress_labels_tools_and_delegation(self) -> None:
        def event(part: dict) -> str:
            return json.dumps({"type": "assistant", "message": {"content": [part]}})

        self.assertEqual(
            ctxgit.claude_stream_progress(
                event({"type": "tool_use", "name": "Write", "input": {"file_path": "/x/deck.html"}})
            ),
            "Using tool: Write · /x/deck.html",
        )
        self.assertEqual(
            ctxgit.claude_stream_progress(
                event(
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "input": {"subagent_type": "explore", "description": "market size"},
                    }
                )
            ),
            "Delegating to subagent: explore · market size",
        )
        # Regression: a parallel batch arrives as several tool_use blocks in ONE message.
        # Reporting only the first hid the fan-out from the log and the modal.
        batch = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "dispatching"},
                        {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "executor", "description": "a.md"}},
                        {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "executor", "description": "b.md"}},
                        {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "writer", "description": "c.md"}},
                    ]
                },
            }
        )
        line = ctxgit.claude_stream_progress(batch)
        from orchestration.transcript import delegations_from_event

        self.assertEqual(len(delegations_from_event(line)), 3)
        self.assertEqual(
            [item["role"] for item in delegations_from_event(line)],
            ["executor", "executor", "writer"],
        )
        self.assertEqual(ctxgit.claude_stream_progress(event({"type": "text", "text": "working"})), "working")
        # internal plumbing and noise stay out of the event log
        self.assertEqual(
            ctxgit.claude_stream_progress(event({"type": "tool_use", "name": "StructuredOutput", "input": {}})),
            "",
        )
        self.assertEqual(ctxgit.claude_stream_progress(json.dumps({"type": "system", "subtype": "init"})), "")
        self.assertEqual(ctxgit.claude_stream_progress("not json"), "")


class TeamPipelineTurnTest(unittest.TestCase):
    def _project(self, tmp: str, provider: str = "claude"):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        ctxgit.write_provider_config(root, {"provider": provider})
        return root, store

    def test_turn_refuses_non_claude_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp, provider="codex")
            with self.assertRaises(ValueError):
                ctxgit.run_team_pipeline_turn(root, store, "b1", "build it")

    def test_turn_records_history_artifacts_and_pipeline_metadata(self) -> None:
        original = ctxgit.call_claude_agent
        verdicts = iter([{"verdict": "PASS", "evidence": "fresh output", "requiredChanges": []}])

        def fake_agent(root, request, *, cwd, progress=None):
            if request.label == "team-plan":
                return orch.AgentReply(
                    data={
                        "summary": "Two tasks",
                        "tasks": [
                            {"id": "t1", "title": "a", "brief": "b", "acceptance": "c", "role": "executor"},
                            {"id": "t2", "title": "d", "brief": "e", "acceptance": "f", "role": "writer"},
                        ],
                    }
                )
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["works"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(data=next(verdicts))
            return orch.AgentReply(text=f"{request.role} ok")

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.call_claude_agent = fake_agent
            try:
                events: list[str] = []
                ctxgit.run_team_pipeline_turn(
                    root, store, "b1", "Build the thing", progress=events.append
                )
            finally:
                ctxgit.call_claude_agent = original

            history = list(store.iter_history("b1"))
            user = [item for item in history if item["role"] == "user"][-1]
            assistant = [item for item in history if item["role"] == "assistant"][-1]

            self.assertEqual(user["mode"], "team-pipeline")
            self.assertEqual(user["turnId"], assistant["turnId"])

            meta = assistant["teamPipeline"]
            self.assertEqual(meta["phase"], orch.PHASE_COMPLETE)
            self.assertEqual(meta["verdict"], "PASS")
            self.assertEqual(meta["tasksCompleted"], 2)
            self.assertEqual(meta["fixAttempts"], 0)
            self.assertEqual(
                meta["phaseHistory"],
                ["team-plan", "team-prd", "team-exec", "team-verify", "complete"],
            )
            self.assertEqual(
                sorted(item["kind"] for item in assistant["artifacts"]),
                ["team-plan", "team-prd", "team-verify"],
            )
            for item in assistant["artifacts"]:
                self.assertFalse(Path(item["path"]).is_absolute())
                self.assertTrue((root / item["path"]).exists())
            self.assertTrue(any("team-plan" in message for message in events))

    def test_turn_reports_a_failed_pipeline_instead_of_raising(self) -> None:
        original = ctxgit.call_claude_agent

        def fake_agent(root, request, *, cwd, progress=None):
            if request.label == "team-plan":
                return orch.AgentReply(
                    data={
                        "summary": "one task",
                        "tasks": [
                            {"id": "t1", "title": "a", "brief": "b", "acceptance": "c", "role": "executor"}
                        ],
                    }
                )
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["works"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(
                    data={"verdict": "FAIL", "evidence": "no", "requiredChanges": ["again"]}
                )
            return orch.AgentReply(text="ok")

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.call_claude_agent = fake_agent
            try:
                ctxgit.run_team_pipeline_turn(root, store, "b1", "never passes")
            finally:
                ctxgit.call_claude_agent = original

            assistant = [item for item in store.iter_history("b1") if item["role"] == "assistant"][-1]
            self.assertEqual(assistant["teamPipeline"]["phase"], orch.PHASE_FAILED)
            self.assertEqual(assistant["teamPipeline"]["fixAttempts"], 4)
            self.assertIn("Outstanding", assistant["text"])


class OrchestrationLogTest(unittest.TestCase):
    """The record of how the agents produced an output."""

    def _project(self, tmp: str, mode: str = "omc"):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        ctxgit.write_provider_config(root, {"provider": "claude", "orchestration": mode})
        return root, store

    def test_mode_resolves_and_falls_back_to_the_old_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp, mode="legacy")
            self.assertEqual(ctxgit.orchestration_mode(root), "legacy")

            config_path = root / ".ctxgit" / "config.json"
            config = json.loads(config_path.read_text())
            config["llm"]["claude"]["orchestration"] = "omc"
            config_path.write_text(json.dumps(config))
            self.assertEqual(ctxgit.orchestration_mode(root), "omc")

            # a config written before the mode existed still works
            del config["llm"]["claude"]["orchestration"]
            config["llm"]["claude"]["subagents"] = True
            config_path.write_text(json.dumps(config))
            self.assertEqual(ctxgit.orchestration_mode(root), "omc")

    def test_invalid_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            with self.assertRaises(ValueError):
                ctxgit.write_provider_config(root, {"provider": "claude", "orchestration": "nope"})

    def test_team_turn_records_every_stage_and_links_it_from_history(self) -> None:
        original = ctxgit.call_claude_agent

        def fake_agent(root, request, *, cwd, progress=None):
            if request.label == "team-plan":
                return orch.AgentReply(
                    data={
                        "summary": "s",
                        "tasks": [
                            {"id": "t1", "title": "a", "brief": "b", "acceptance": "c", "role": "executor"}
                        ],
                    }
                )
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["x"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(data={"verdict": "PASS", "evidence": "e", "requiredChanges": []})
            return orch.AgentReply(text="executor did it")

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.call_claude_agent = fake_agent
            try:
                ctxgit.run_team_pipeline_turn(root, store, "b1", "Build it")
            finally:
                ctxgit.call_claude_agent = original

            assistant = [item for item in store.iter_history("b1") if item["role"] == "assistant"][-1]
            self.assertIn("orchestrationLog", assistant)
            log = json.loads((root / assistant["orchestrationLog"]).read_text())
            self.assertEqual(log["mode"], "team-pipeline")
            self.assertEqual(log["turnId"], assistant["turnId"])
            roles = [entry["role"] for entry in log["entries"]]
            self.assertEqual(roles, ["planner", "analyst", "executor", "verifier"])
            stages = [entry["stage"] for entry in log["entries"]]
            self.assertEqual(stages, ["team-plan", "team-prd", "team-exec", "team-verify"])
            # both sides of each exchange are kept, which is the point
            for entry in log["entries"]:
                self.assertTrue(entry["prompt"])
                self.assertTrue(entry["reply"])

    def test_a_failed_worker_is_still_recorded(self) -> None:
        original = ctxgit.call_claude_agent

        def fake_agent(root, request, *, cwd, progress=None):
            if request.label == "team-plan":
                return orch.AgentReply(
                    data={
                        "summary": "s",
                        "tasks": [
                            {"id": "t1", "title": "a", "brief": "b", "acceptance": "c", "role": "executor"}
                        ],
                    }
                )
            if request.label == "team-prd":
                return orch.AgentReply(data={"acceptanceCriteria": ["x"], "outOfScope": []})
            if request.label == "team-verify":
                return orch.AgentReply(data={"verdict": "PASS", "evidence": "e", "requiredChanges": []})
            raise RuntimeError("worker exploded")

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.call_claude_agent = fake_agent
            try:
                ctxgit.run_team_pipeline_turn(root, store, "b1", "Build it")
            finally:
                ctxgit.call_claude_agent = original

            assistant = [item for item in store.iter_history("b1") if item["role"] == "assistant"][-1]
            log = json.loads((root / assistant["orchestrationLog"]).read_text())
            failed = [entry for entry in log["entries"] if entry["meta"].get("failed")]
            self.assertEqual(len(failed), 1)
            self.assertIn("worker exploded", failed[0]["reply"])

    def test_chat_turn_reconstructs_a_subagent_timeline_from_the_stream(self) -> None:
        # The lead's fan-out only exists in the raw stream, tagged with
        # parent_tool_use_id; the turn must turn that into a timeline the modal reads.
        def ev(ts, obj):
            obj["timestamp"] = ts
            return json.dumps(obj)

        stream_lines = [
            ev("2026-01-01T00:00:00.000Z", {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Agent", "id": "AA",
                 "input": {"subagent_type": "scientist", "description": "review ML"}},
                {"type": "tool_use", "name": "Agent", "id": "BB",
                 "input": {"subagent_type": "architect", "description": "review ontology"}},
            ]}}),
            ev("2026-01-01T00:00:01.000Z", {"type": "assistant", "parent_tool_use_id": "AA",
                "subagent_type": "scientist", "message": {"content": [
                    {"type": "tool_use", "name": "WebSearch", "input": {"query": "DAgger"}}]}}),
            ev("2026-01-01T00:00:01.500Z", {"type": "assistant", "parent_tool_use_id": "BB",
                "subagent_type": "architect", "message": {"content": [
                    {"type": "tool_use", "name": "WebSearch", "input": {"query": "SHACL"}}]}}),
            ev("2026-01-01T00:00:06.000Z", {"type": "assistant", "parent_tool_use_id": "AA",
                "subagent_type": "scientist", "message": {"content": [
                    {"type": "text", "text": "ML claims mostly hold."}]}}),
            ev("2026-01-01T00:00:06.500Z", {"type": "assistant", "parent_tool_use_id": "BB",
                "subagent_type": "architect", "message": {"content": [
                    {"type": "text", "text": "SHACL usage is sound."}]}}),
        ]

        original_stream = ctxgit.run_process_with_progress
        original_run = ctxgit.subprocess.run

        def fake_stream(cmd, cwd, timeout, progress, stdin_text=None, event_formatter=None):
            sink = getattr(progress, "event_sink", None)
            if sink:
                for line in stream_lines:
                    sink(json.loads(line))
            return FakeCompleted(
                stdout=structured_result({"assistant": "done", "artifacts": [], "approvalRequests": []})
            )

        def fake_run(cmd, **_kwargs):
            if "auth" in cmd and "status" in cmd:
                return FakeCompleted(stdout="Logged in")
            return FakeCompleted(stdout=structured_result({"assistant": "done", "artifacts": [], "approvalRequests": []}))

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.run_process_with_progress = fake_stream
            ctxgit.subprocess.run = fake_run
            try:
                ctxgit.run_chat_turn(root, store, "b1", "do it", provider="claude", progress=lambda _m: None)
            finally:
                ctxgit.run_process_with_progress = original_stream
                ctxgit.subprocess.run = original_run

            assistant = [item for item in store.iter_history("b1") if item["role"] == "assistant"][-1]
            self.assertIn("orchestrationLog", assistant)
            log = json.loads((root / assistant["orchestrationLog"]).read_text())
            self.assertEqual(log["mode"], "chat")
            subs = log["timeline"]["subagents"]
            self.assertEqual([s["type"] for s in subs], ["scientist", "architect"])
            # each subagent's own work and reply are captured
            self.assertEqual(subs[0]["summary"], "ML claims mostly hold.")
            self.assertTrue(any(e["kind"] == "tool" for e in subs[0]["events"]))
            # the two ran concurrently: their active windows overlap
            a, b = subs[0], subs[1]
            overlap = min(a["endAt"], b["endAt"]) - max(a["startAt"], b["startAt"])
            self.assertGreater(overlap, 0)

    def test_delegation_parser_handles_batches_and_ignores_other_events(self) -> None:
        from orchestration.transcript import delegations_from_event

        self.assertEqual(
            delegations_from_event("Delegating to subagent: verifier · check the deck"),
            [{"role": "verifier", "description": "check the deck"}],
        )
        self.assertEqual(
            delegations_from_event("Delegating to subagent: planner"),
            [{"role": "planner", "description": ""}],
        )
        # a parallel batch: every one of them counts
        self.assertEqual(
            delegations_from_event(
                "Delegating to subagent: executor · a ;; executor · b ;; writer · c"
            ),
            [
                {"role": "executor", "description": "a"},
                {"role": "executor", "description": "b"},
                {"role": "writer", "description": "c"},
            ],
        )
        self.assertEqual(delegations_from_event("Using tool: Write · /x.html"), [])
        self.assertEqual(delegations_from_event("Claude Code is working"), [])

    def test_long_prompts_are_excerpted_not_dropped(self) -> None:
        from orchestration.transcript import excerpt

        short = excerpt("hello")
        self.assertEqual(short, "hello")
        long_text = "x" * 9000
        trimmed = excerpt(long_text, 100)
        self.assertLess(len(trimmed), 400)
        self.assertIn("omitted", trimmed)


class SequenceInterjectionTest(unittest.TestCase):
    def _room(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("alpha")
        store.create_branch("beta")
        store.create_sequence_room(
            ["alpha", "beta"],
            "room",
            "Room",
            system_prompts=["", ""],
            access_modes=["info-chat", "info-chat"],
            max_agent_replies=4,
        )
        return root, store

    def test_interjection_requires_a_sequence_room_and_a_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, store = self._room(tmp)
            with self.assertRaises(ValueError):
                store.append_sequence_interjection("alpha", "hi")
            with self.assertRaises(ValueError):
                store.append_sequence_interjection("room", "   ")

    def test_interjection_lands_before_the_in_flight_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, store = self._room(tmp)
            store.append_history("room", "user", "kickoff", extra={"mode": "sequence-room"})

            # the agent is "generating": its reply is only appended once it finishes
            def agent_reply() -> None:
                time.sleep(0.05)
                store.append_history("room", "assistant", "agent reply", extra={"mode": "sequence-room"})

            worker = threading.Thread(target=agent_reply)
            worker.start()
            record = store.append_sequence_interjection("room", "wait, focus on X", run_mode="send")
            worker.join()

            texts = [item["text"] for item in store.iter_history("room")]
            self.assertLess(texts.index("wait, focus on X"), texts.index("agent reply"))
            self.assertTrue(record["interjection"])
            self.assertEqual(record["mode"], "sequence-room")
            self.assertEqual(record["sequenceRunMode"], "send")

    def test_concurrent_appends_do_not_corrupt_history_or_metadata(self) -> None:
        # An interjection lands while a sequence-room turn is appending an agent
        # reply, so the same branch gets concurrent writers. Both history.jsonl and
        # branch.json must survive it.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            errors: list[BaseException] = []

            def append(index: int) -> None:
                try:
                    store.append_history("room", "user", f"msg-{index}", extra={"mode": "sequence-room"})
                except BaseException as exc:  # noqa: BLE001 - a torn metadata read exits the thread
                    errors.append(exc)

            threads = [threading.Thread(target=append, args=(i,)) for i in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            records = list(store.iter_history("room"))
            self.assertEqual(len(records), 20)
            self.assertEqual({item["text"] for item in records}, {f"msg-{i}" for i in range(20)})
            # branch.json must still be readable, not a half-written file
            meta = json.loads((root / "contexts" / "branches" / "room" / "branch.json").read_text())
            self.assertEqual(meta["id"], "room")
            self.assertTrue(meta["updatedAt"])

    def test_metadata_writes_are_atomic_under_concurrent_readers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            meta_path = root / "contexts" / "branches" / "room" / "branch.json"
            stop = threading.Event()
            read_errors: list[BaseException] = []

            def reader() -> None:
                while not stop.is_set():
                    try:
                        json.loads(meta_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as exc:  # a torn read
                        read_errors.append(exc)
                    except OSError:
                        pass

            watcher = threading.Thread(target=reader)
            watcher.start()
            try:
                for _ in range(50):
                    store.touch_branch("room")
            finally:
                stop.set()
                watcher.join()

            self.assertEqual(read_errors, [])


class RevealBranchDirTest(unittest.TestCase):
    def test_open_path_uses_the_platform_file_browser(self) -> None:
        calls: list[list[str]] = []

        class FakePopen:
            def __init__(self, args, *a, **k) -> None:
                calls.append(args)

        original_popen = ctxgit.subprocess.Popen
        original_platform = ctxgit.sys.platform
        ctxgit.subprocess.Popen = FakePopen
        try:
            ctxgit.open_path_in_file_browser(Path("/tmp/somewhere"))
        finally:
            ctxgit.subprocess.Popen = original_popen
            ctxgit.sys.platform = original_platform

        self.assertEqual(len(calls), 1)
        self.assertIn("/tmp/somewhere", calls[0])
        self.assertIn(calls[0][0], {"open", "explorer", "xdg-open"})

    def test_branch_dir_resolves_within_the_project_and_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            store.create_branch("b1")

            directory = store.branch_paths_for_read("b1").root
            self.assertTrue(directory.is_dir())
            self.assertTrue(ctxgit.path_is_within(root, directory))

            with self.assertRaises(SystemExit):
                store.branch_paths_for_read("../../etc")


if __name__ == "__main__":
    unittest.main()
