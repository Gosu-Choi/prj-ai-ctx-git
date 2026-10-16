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
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402,F401  (must precede loading ctxgit: keeps tests out of the real ~/.ctxgit)

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
            # Subagents enabled: Task is available, i.e. not on the denylist.
            if "--disallowedTools" in cmd:
                self.assertNotIn("Task", cmd[cmd.index("--disallowedTools") + 1])
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
            # No subagents: Task is gated, i.e. on the denylist.
            self.assertIn("--disallowedTools", cmd)
            self.assertIn("Task", cmd[cmd.index("--disallowedTools") + 1])
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

    def test_full_access_drops_the_auto_mode_classifier_on_writable_sessions(self) -> None:
        """A writable session normally runs under Claude Code's auto-mode
        classifier, which decides per command and is not deterministic — the same
        command is allowed one day and blocked the next, with nobody present to
        approve the prompt. `danger-full-access` is the opt-out, and it is the same
        value Codex already takes, so one setting covers both providers."""
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp, sandbox="workspace-write")
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "auto")

        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp, sandbox="danger-full-access")
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "bypassPermissions")

        with tempfile.TemporaryDirectory() as tmp:
            # Read-only sessions always bypassed: the tool denylist carries the
            # restriction, so the classifier has nothing left to decide.
            root, store = self._project(tmp, sandbox="read-only")
            cmd = self._capture_chat_command(root, store, "b1")
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "bypassPermissions")

    def test_pipeline_stages_follow_the_same_permission_setting(self) -> None:
        # A team turn that cannot merge is as stuck as a chat turn that cannot.
        for sandbox, expected in (
            ("workspace-write", "auto"),
            ("danger-full-access", "bypassPermissions"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                root, _ = self._project(tmp, sandbox=sandbox)
                seen: list[list[str]] = []
                self._run_stage_agent(
                    root,
                    seen,
                    json.dumps({"type": "result", "structured_output": {"verdict": "PASS"}}),
                    role="executor",
                    prompt="ship it",
                    writable=True,
                    schema={"type": "object"},
                    label="team-exec",
                )
                cmd = seen[0]
                self.assertEqual(cmd[cmd.index("--permission-mode") + 1], expected)

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
            # verifier declares disallowedTools: Write, Edit — and no worker re-delegates.
            # The restriction is stated as a denylist because `--tools` would also
            # drop MCP tools from the stage.
            self.assertNotIn("--tools", cmd)
            allowed = cmd[cmd.index("--allowedTools") + 1]
            disallowed = cmd[cmd.index("--disallowedTools") + 1]
            self.assertNotIn("Task", allowed)
            self.assertNotIn("Write", allowed)
            self.assertIn("Task", disallowed.split(","))
            self.assertIn("Write", disallowed.split(","))
            self.assertEqual(reply.data, {"verdict": "PASS"})
            self.assertEqual(reply.text, "raw text")

    def _stage_model(self, tmp: str, role: str, **provider) -> str:
        root, _ = self._project(tmp, **provider)
        seen: list[list[str]] = []
        self._run_stage_agent(
            root,
            seen,
            json.dumps({"type": "result", "structured_output": {"verdict": "PASS"}}),
            role=role,
            prompt="check it",
            writable=True,
            schema={"type": "object"},
            label="team-verify",
        )
        cmd = seen[0]
        return cmd[cmd.index("--model") + 1]

    def test_selecting_fable_reaches_the_roles_that_asked_for_the_top_tier(self) -> None:
        # A role's tier is relative: the library says "opus" for "the frontier
        # model", so picking Fable has to reach those stages instead of leaving the
        # whole pipeline on Opus while only the chat turn upgraded.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._stage_model(tmp, "planner", model="fable"), "fable")
        with tempfile.TemporaryDirectory() as tmp:
            # ...and the cheap roles stay cheap.
            self.assertEqual(self._stage_model(tmp, "verifier", model="fable"), "sonnet")
        with tempfile.TemporaryDirectory() as tmp:
            # The 1M context choice carries through to the frontier stages too.
            self.assertEqual(self._stage_model(tmp, "planner", model="opus[1m]"), "opus[1m]")

    def test_a_cheaper_selection_caps_the_roles_that_asked_for_more(self) -> None:
        # Picking Haiku is a budget decision; a role asking for Opus must not
        # quietly spend it anyway.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._stage_model(tmp, "planner", model="haiku"), "haiku")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._stage_model(tmp, "verifier", model="haiku"), "haiku")

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


class ExtensionStalenessTest(unittest.TestCase):
    def test_fingerprint_changes_when_an_extension_file_changes(self) -> None:
        # Python imports an extension module once per process, so an edit only
        # lands on restart. The fingerprint is what lets the UI say so.
        before = ctxgit.extensions_fingerprint()
        self.assertEqual(before, ctxgit.extensions_fingerprint())  # stable

        target = Path(ctxgit.extensions.__file__).resolve().parent / "adit" / "servers.json"
        original = target.read_bytes()
        try:
            time.sleep(0.01)
            target.write_bytes(original + b"\n")
            self.assertNotEqual(before, ctxgit.extensions_fingerprint())
        finally:
            target.write_bytes(original)

    def test_extensions_endpoint_reports_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            handler = ctxgit.make_handler(ctxgit.ProjectState(root), auth_required=False)
            with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with urllib.request.urlopen(f"{base_url}/api/extensions", timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
            self.assertIn("stale", payload)
            self.assertIsInstance(payload["stale"], bool)
            # "Changed" is only actionable next to when this process loaded, so
            # both timestamps ship together.
            self.assertTrue(payload["loadedAt"])
            self.assertTrue(payload["changedAt"])
            for ext in payload["extensions"]:
                self.assertTrue(ext["updatedAt"], ext["id"])

    def test_version_payload_reports_the_pending_edit_and_commit(self) -> None:
        target = Path(ctxgit.extensions.__file__).resolve().parent / "adit" / "servers.json"
        original = target.read_bytes()
        try:
            # No assertion on `before["stale"]`: a sibling test touches this same
            # file, and restoring it moves the mtime, so the process may already
            # be stale by now. What must hold is how the fields move.
            before = ctxgit.extensions_version_payload()
            time.sleep(0.01)
            target.write_bytes(original + b"\n")
            after = ctxgit.extensions_version_payload()
            self.assertTrue(after["stale"])
            # loadedAt pins the running version; changedAt moves with the edit.
            self.assertEqual(after["loadedAt"], before["loadedAt"])
            self.assertGreaterEqual(after["changedAt"], before["changedAt"])
            self.assertGreater(after["changedAt"], after["loadedMtime"])
            if after["commit"]:
                # An uncommitted edit makes the commit date a misleading
                # "last updated", so it is flagged.
                self.assertTrue(after["commit"]["dirty"])
        finally:
            target.write_bytes(original)


class CodexTeamPipelineTest(unittest.TestCase):
    """The team pipeline has to run on whichever provider the project is set to.

    Before this, `/api/team/start` always ran Claude agents. On a Codex project the
    stage either failed at the login check or silently ran on the other provider —
    the pipeline is picked in the UI, so nothing told the user which model answered.
    """

    def _project(self, tmp: str, provider: str = "codex"):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        ctxgit.write_provider_config(root, {"provider": provider})
        return root, store

    def _run(self, root: Path, seen: list, stdout: str, **request_kwargs):
        original_run = ctxgit.subprocess.run
        original_login = ctxgit.codex_login_status

        def fake_run(cmd, **kwargs):
            seen.append({"cmd": cmd, "input": kwargs.get("input", "")})
            # Codex writes the answer to --output-last-message, not stdout.
            out = cmd[cmd.index("--output-last-message") + 1]
            Path(out).write_text(stdout, encoding="utf-8")
            return FakeCompleted(stdout="")

        ctxgit.subprocess.run = fake_run
        ctxgit.codex_login_status = lambda _root: {"ok": True, "message": ""}
        try:
            return ctxgit.call_provider_agent(
                root, orch.AgentRequest(**request_kwargs), cwd=root
            )
        finally:
            ctxgit.subprocess.run = original_run
            ctxgit.codex_login_status = original_login

    def test_codex_project_runs_the_stage_on_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            seen: list[dict] = []
            reply = self._run(
                root,
                seen,
                json.dumps({"verdict": "PASS"}),
                role="verifier",
                prompt="check it",
                writable=True,
                schema={"type": "object"},
                label="team-verify",
            )
            cmd = seen[0]["cmd"]
            self.assertIn("exec", cmd)
            self.assertIn("--output-schema", cmd)
            # no --append-system-prompt on this CLI: the role is prepended instead
            self.assertNotIn("--append-system-prompt", cmd)
            self.assertIn("You are Verifier", seen[0]["input"])
            self.assertIn("check it", seen[0]["input"])
            self.assertEqual(reply.data, {"verdict": "PASS"})

    def test_a_read_only_role_runs_read_only_even_in_a_writable_turn(self) -> None:
        # Codex has no per-tool allowlist, so the role's scope is carried by the
        # sandbox. A verifier must not be able to edit what it is verifying.
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            seen: list[dict] = []
            self._run(
                root, seen, json.dumps({"verdict": "PASS"}),
                role="verifier", prompt="check", writable=True,
                schema={"type": "object"}, label="v",
            )
            cmd = seen[0]["cmd"]
            self.assertEqual(cmd[cmd.index("--sandbox") + 1], "read-only")

    def test_role_tier_is_mapped_to_the_codex_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            seen: list[dict] = []
            self._run(
                root, seen, json.dumps({"verdict": "PASS"}),
                role="verifier", prompt="check", writable=True,
                schema={"type": "object"}, label="v",
            )
            cmd = seen[0]["cmd"]
            # the verifier role declares Claude's "sonnet" tier
            self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.6-terra")

    def test_claude_project_still_runs_the_stage_on_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp, provider="claude")
            original = ctxgit.subprocess.run
            seen: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                if "auth" in cmd and "status" in cmd:
                    return FakeCompleted(stdout="Logged in")
                seen.append(cmd)
                return FakeCompleted(
                    stdout=json.dumps(
                        {"type": "result", "result": "ok", "structured_output": {"verdict": "PASS"}}
                    )
                )

            ctxgit.subprocess.run = fake_run
            try:
                ctxgit.call_provider_agent(
                    root,
                    orch.AgentRequest(
                        role="verifier", prompt="check", writable=True,
                        schema={"type": "object"}, label="v",
                    ),
                    cwd=root,
                )
            finally:
                ctxgit.subprocess.run = original
            self.assertIn("--append-system-prompt", seen[0])


class SubagentMcpReachTest(unittest.TestCase):
    """Delegated work must reach the same integrations the lead can reach.

    Regression guard: MCP was wired into the lead's own turn only. A worker then
    ran without `--mcp-config` and with `--tools` (an allowlist that drops MCP
    tools), so anything delegated came back as "I could not find that data" —
    indistinguishable from the data genuinely not existing.
    """

    def test_pool_offers_mcp_tools_to_subagents(self) -> None:
        pool = orch.subagent_tool_pool(
            writable=False, web_search=False, mcp_tools=["mcp__adit__console_read"]
        )
        self.assertIn("mcp__adit__console_read", pool)
        # the built-in restriction still holds
        self.assertNotIn("Write", pool)
        self.assertNotIn("Task", pool)

    def test_pool_without_extensions_is_unchanged(self) -> None:
        self.assertEqual(
            orch.subagent_tool_pool(writable=True, web_search=True),
            orch.subagent_tool_pool(writable=True, web_search=True, mcp_tools=[]),
        )


class ExternalExtensionMcpTest(unittest.TestCase):
    """An extension may forward MCP servers it does not implement (e.g. `adit`)."""

    def test_external_servers_are_launched_through_ctxgit_not_directly(self) -> None:
        # Provider wiring puts these specs on argv, and argv is world-readable via
        # `ps`. Secrets must therefore reach the server through the launcher's
        # environment, never through the command line.
        servers = ctxgit.active_extension_mcp_servers()
        adit = ctxgit.extensions.get_extension("adit")
        declared = ctxgit.extensions.mcp_servers(adit)
        if not declared:
            self.skipTest("no Adit MCP server configured on this machine")
        for name in declared:
            self.assertIn(name, servers)
            spec = servers[name]
            if spec.get("url"):
                # A remote server is an endpoint and nothing else: the provider CLI
                # holds the OAuth token, so no credential exists to leak onto argv.
                self.assertNotIn("command", spec)
                self.assertNotIn("env", spec)
                continue
            self.assertEqual(spec["command"], sys.executable)
            self.assertIn("mcp-server", spec["args"])
            self.assertNotIn("env", spec)
            self.assertNotIn("cwd", spec)

    def test_no_secret_reaches_the_command_line_on_either_provider(self) -> None:
        declared = ctxgit.extensions.mcp_servers(ctxgit.extensions.get_extension("adit"))
        secrets = [
            str(v) for spec in declared.values()
            for k, v in (spec.get("env") or {}).items()
            if "SECRET" in k.upper() or "TOKEN" in k.upper()
        ]
        if not secrets:
            self.skipTest("no Adit MCP secret configured on this machine")
        codex_cmd: list[str] = []
        ctxgit.apply_codex_extension_mcps(codex_cmd, Path("."))
        surface = json.dumps(ctxgit.active_extension_mcp_config()) + " ".join(codex_cmd)
        for secret in secrets:
            self.assertNotIn(secret, surface)

    def test_unconfigured_server_is_skipped_not_offered_broken(self) -> None:
        adit = ctxgit.extensions.get_extension("adit")
        ready = set(ctxgit.extensions.mcp_servers(adit))
        for row in adit.server_status():
            # Every declared server is either offered, or withheld with a reason.
            self.assertEqual(row["ready"], row["id"] in ready)
            if not row["ready"]:
                self.assertTrue(row["reason"])


class SupersededHostMcpTest(unittest.TestCase):
    def test_hosted_google_servers_are_denied_on_every_claude_path(self) -> None:
        # ctxgit deliberately omits --strict-mcp-config so a server the user
        # configured in their own Claude Code (chrome-devtools) works here too.
        # The hosted gmail/drive servers ride in through that same door carrying
        # write tools, which would undo the read-only Google extension, so they
        # must be denied whether or not the turn is writable.
        for writable in (False, True):
            for web_search in (False, True):
                denied = ctxgit.claude_disallowed_tools(
                    writable=writable, web_search=web_search
                ).split(",")
                self.assertIn("mcp__gmail", denied)
                self.assertIn("mcp__drive", denied)
                # Denying by server name must not catch any other inherited
                # server, and must never touch ctxgit's own Google extension.
                self.assertFalse([d for d in denied if d.startswith("mcp__chrome")])
                self.assertFalse([d for d in denied if d.startswith("mcp__google")])

    def test_ctxgit_google_extension_exposes_only_read_tools(self) -> None:
        google = [n for n in ctxgit.active_extension_mcp_tool_names()
                  if n.startswith("mcp__google__")]
        if not google:
            self.skipTest("google extension not configured on this machine")
        # e.g. mcp__google__gmail_search, mcp__google__drive_read_file — a write
        # verb (create/copy/label/send) must never appear.
        for name in google:
            self.assertRegex(name, r"_(search|get|list|read)(_|$)")


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

        def fake_stream(
            cmd, cwd, timeout, progress, stdin_text=None, event_formatter=None, stdin_channel=None
        ):
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


class StreamedStdinTest(unittest.TestCase):
    """Deciding when a steered turn's stdin can be closed.

    A message dropped into a running turn lands in one of two ways and the CLI does
    not say which in advance: inside the tool loop it joins that turn, otherwise it
    becomes a follow-up turn. Closing stdin on the first result would silently drop
    the second case, so the replay echo is what the close waits on.
    """

    def _user_echo(self, text: str) -> str:
        return json.dumps(
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        )

    def _tool_result_echo(self) -> str:
        return json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
                },
            }
        )

    def test_a_plain_turn_closes_on_its_result(self) -> None:
        channel = ctxgit.StreamedStdin()
        self.assertFalse(channel.observe('{"type":"assistant"}'))
        self.assertTrue(channel.observe('{"type":"result","result":"done"}'))

    def test_an_unconsumed_interjection_holds_stdin_open(self) -> None:
        channel = ctxgit.StreamedStdin()
        channel.queue("actually, skip the rest")
        # The turn reports a result before the CLI has taken the message: it is
        # about to run as a follow-up turn, so stdin must stay open for it.
        self.assertFalse(channel.observe('{"type":"result","result":"first"}'))
        # The echo only marks it taken; the close decision waits for that turn's
        # own result.
        self.assertFalse(channel.observe(self._user_echo("actually, skip the rest")))
        self.assertTrue(channel.observe('{"type":"result","result":"second"}'))

    def test_a_consumed_interjection_lets_the_turn_end(self) -> None:
        channel = ctxgit.StreamedStdin()
        channel.queue("skip the rest")
        # Steered inside the tool loop: taken first, then one result for the turn.
        self.assertFalse(channel.observe(self._user_echo("skip the rest")))
        self.assertTrue(channel.observe('{"type":"result","result":"done"}'))

    def test_tool_results_are_not_mistaken_for_the_echo(self) -> None:
        channel = ctxgit.StreamedStdin()
        channel.queue("skip the rest")
        self.assertFalse(channel.observe(self._tool_result_echo()))
        self.assertFalse(channel.observe('{"type":"result","result":"done"}'))

    def test_drain_hands_over_each_message_once(self) -> None:
        channel = ctxgit.StreamedStdin()
        channel.queue("first")
        channel.queue("  ")  # blank input is not a message
        channel.queue("second")
        lines = channel.drain()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["message"]["content"][0]["text"], "first")
        self.assertTrue(lines[0].endswith("\n"))
        self.assertEqual(channel.drain(), [])


class SequenceRoomInterjectionTest(unittest.TestCase):
    """A room's interjection has to reach the agent that is speaking now.

    It used to only be appended to history, so the speaking agent never heard it —
    the one after it did, by reading the transcript. A room is one job running a
    chain of agent processes, so the job's queue has to travel down to whichever
    process is live.
    """

    def test_the_room_agent_inherits_the_job_interjection_queue(self) -> None:
        handed: list[str] = []

        def progress(_message: str) -> None:
            return None

        progress.take_interjections = lambda: ["mid-run steer"]  # type: ignore[attr-defined]
        progress.cancelled = lambda: False  # type: ignore[attr-defined]

        wrapped = ctxgit.stream_capturing_progress(orch.StreamTranscript(), progress)
        take = getattr(wrapped, "take_interjections", None)
        self.assertIsNotNone(take, "the room agent cannot be spoken to without this")
        handed.extend(take())
        self.assertEqual(handed, ["mid-run steer"])
        # Cancellation still rides along; the wrapper carries both.
        self.assertFalse(getattr(wrapped, "cancelled")())

    def test_a_queue_survives_until_a_process_asks_for_it(self) -> None:
        # Queued between two replies, taken by the next agent that starts.
        registry = ctxgit.JobStore.__new__(ctxgit.JobStore)
        registry._lock = threading.RLock()
        registry._jobs = {"j1": {"id": "j1", "status": "running"}}
        registry.persist_locked = lambda _job: None
        registry.snapshot = lambda job_id, root=None: {"id": job_id}
        registry.load_locked = lambda job_id, root=None: None

        registry.interject("j1", "hold on")
        self.assertEqual(registry.take_interjections("j1"), ["hold on"])
        # Taken once only: a second agent must not replay it.
        self.assertEqual(registry.take_interjections("j1"), [])

    def test_a_finished_job_refuses_instead_of_swallowing_the_message(self) -> None:
        registry = ctxgit.JobStore.__new__(ctxgit.JobStore)
        registry._lock = threading.RLock()
        registry._jobs = {"j1": {"id": "j1", "status": "done"}}
        registry.persist_locked = lambda _job: None
        registry.snapshot = lambda job_id, root=None: {"id": job_id}
        registry.load_locked = lambda job_id, root=None: None

        result = registry.interject("j1", "too late")
        self.assertEqual(result.get("error"), "job_not_running")


class ChatEnvelopeRecoveryTest(unittest.TestCase):
    """When the reply wraps the envelope in something else.

    The contract is "return JSON only". When a reply adds a line of preamble or
    puts the object in a fenced block, the whole thing used to be stored verbatim,
    so the chat showed raw JSON with literal \\n where the answer should be. This is
    the strict-schema fallback's normal failure shape, so it has to be recovered.
    """

    ENVELOPE = json.dumps(
        {"assistant": "코드는 통일됐다.", "artifacts": [], "approvalRequests": []},
        ensure_ascii=False,
    )

    def test_preamble_before_the_object(self) -> None:
        raw = "확인 끝. 정리해서 답한다.\n\n" + self.ENVELOPE
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], "코드는 통일됐다.")

    def test_object_inside_a_fenced_block(self) -> None:
        raw = "확인 끝.\n\n```json\n" + self.ENVELOPE + "\n```"
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], "코드는 통일됐다.")

    def test_prose_after_the_object(self) -> None:
        raw = self.ENVELOPE + "\n\n필요하면 더 하겠다."
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], "코드는 통일됐다.")

    def test_an_answer_that_quotes_other_json_is_left_alone(self) -> None:
        # Dev chat quotes config and API payloads constantly. Only an object with a
        # string `assistant` is the envelope; nothing else has that shape.
        answer = '설정은 이렇다:\n```json\n{"port": 5180}\n```'
        raw = json.dumps(
            {"assistant": answer, "artifacts": [], "approvalRequests": []}, ensure_ascii=False
        )
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], answer)

    def test_a_reply_that_is_only_someone_elses_json_stays_raw(self) -> None:
        raw = 'here is the config: {"port": 5180, "mode": "dev"}'
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], raw)

    def test_plain_prose_still_falls_through(self) -> None:
        self.assertEqual(ctxgit.parse_chat_result("그냥 산문이다.")["assistant"], "그냥 산문이다.")

    def test_braces_inside_strings_do_not_cut_the_span_short(self) -> None:
        envelope = json.dumps(
            {"assistant": 'closing brace: "}" here', "artifacts": [], "approvalRequests": []},
            ensure_ascii=False,
        )
        raw = "먼저 한마디.\n\n" + envelope
        self.assertEqual(ctxgit.parse_chat_result(raw)["assistant"], 'closing brace: "}" here')

    def test_recovery_reaches_the_claude_result_path(self) -> None:
        # The same reply as it actually arrives: a stream-json result event whose
        # `result` string carries the preamble.
        stream = json.dumps(
            {"type": "result", "subtype": "success", "result": "확인 끝.\n\n" + self.ENVELOPE}
        )
        self.assertEqual(ctxgit.parse_claude_result(stream)["assistant"], "코드는 통일됐다.")


class SequenceRoomParticipantIntegrityTest(unittest.TestCase):
    """A room that has quietly lost a speaker must not run.

    Observed 2026-08-23: a save while the participant panel was open left one
    usable order, the room ran anyway, and the evaluator answered and graded
    itself for all six replies. The job reported success, the branch got no reply
    anyone wanted, and the run was only visible as "Sequence evaluation 6" in the
    event log. The count check that existed passed, because it counted the raw
    list rather than the orders the room actually speaks from.
    """

    def _room(self, tmp: str, participants: list, speaking_order=None, stop_decider=2):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("room")
        config = {
            "participants": participants,
            "speakingOrder": speaking_order if speaking_order is not None else [1, 2],
            "stopDecider": stop_decider,
            "defaultMaxAgentReplies": 6,
            "minimumEvaluatorRounds": 2,
        }
        store.sequence_room_config = lambda _branch, _config=config: _config
        return root, store

    def _participant(self, order: int, source: str):
        return {"order": order, "sourceBranch": source, "accessMode": "info-chat"}

    def _run(self, root, store):
        return ctxgit.run_sequence_room_turn(root, store, "room", "go")

    def test_two_participants_sharing_an_order_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(
                tmp, [self._participant(2, "a"), self._participant(2, "b")]
            )
            with self.assertRaises(ValueError) as caught:
                self._run(root, store)
            self.assertIn("duplicate order", str(caught.exception))

    def test_a_participant_with_no_order_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(
                tmp, [self._participant(1, "a"), {"sourceBranch": "b", "accessMode": "send"}]
            )
            with self.assertRaises(ValueError) as caught:
                self._run(root, store)
            self.assertIn("no speaking order", str(caught.exception))

    def test_a_lone_speaker_who_is_also_the_evaluator_is_refused(self) -> None:
        # The room's stopDecider is 2 and the saved order names only 2, so that one
        # agent would answer and then grade its own answer, round after round.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(
                tmp,
                [self._participant(1, "a"), self._participant(2, "b")],
                speaking_order=[2],
            )
            with self.assertRaises(ValueError) as caught:
                self._run(root, store)
            self.assertIn("also its evaluator", str(caught.exception))

    def test_a_single_speaker_with_no_evaluator_takes_one_reply_and_stops(self) -> None:
        """Naming one participant and no evaluator is a real setup, not a mistake.

        The integrity check first written here refused any room that resolved to one
        speaker, which also refused this — the "just this one agent, once" case.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(
                tmp,
                [self._participant(1, "a"), self._participant(2, "b")],
                speaking_order=[1],
                stop_decider=None,
            )
            calls: list[str] = []
            original = ctxgit.call_provider_prompt

            def fake(provider, *_args, **_kwargs):
                calls.append(provider)
                return {"assistant": f"reply {len(calls)}"}

            ctxgit.call_provider_prompt = fake
            try:
                result = self._run(root, store)
            finally:
                ctxgit.call_provider_prompt = original
            self.assertEqual(len(calls), 1, "one speaker, one reply")
            self.assertEqual(result["sequenceRun"]["stopReason"].count("speaking-order cycle"), 1)


class ProviderStandingDirectiveParityTest(unittest.TestCase):
    """Whatever governs a turn has to reach both providers the same way.

    Guiding knowledge goes three places on a chat turn — the provider's standing
    instructions, the prompt body, and a reminder after the user message — because
    the body alone did not hold. Room turns went through a different entry point
    that had no standing-instruction channel at all, so on either provider a room
    agent only ever saw guiding as one section of a very long user message.
    """

    def test_the_shared_entry_point_carries_it_to_both_providers(self) -> None:
        seen: dict[str, str] = {}

        original_claude = ctxgit.call_claude_prompt
        original_codex = ctxgit.call_codex_prompt
        ctxgit.call_claude_prompt = lambda *a, **k: seen.setdefault("claude", k.get("system_extra", "")) or {}
        ctxgit.call_codex_prompt = lambda *a, **k: seen.setdefault("codex", k.get("system_extra", "")) or {}
        try:
            for provider in ("claude", "codex"):
                ctxgit.call_provider_prompt(
                    provider, Path("/tmp"), "prompt", writable=False, system_extra="STANDING_RULE"
                )
        finally:
            ctxgit.call_claude_prompt = original_claude
            ctxgit.call_codex_prompt = original_codex

        self.assertEqual(seen.get("claude"), "STANDING_RULE")
        self.assertEqual(seen.get("codex"), "STANDING_RULE")

    def test_codex_puts_it_in_developer_instructions_on_the_exec_path(self) -> None:
        # `codex exec` has no system prompt flag; the native field is where a
        # standing rule stops competing with history inside the user prompt.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            cmd: list[str] = []
            ctxgit.apply_codex_session_config(cmd, root, developer_extra="STANDING_RULE")
            joined = " ".join(cmd)
            self.assertIn("developer_instructions=", joined)
            self.assertIn("STANDING_RULE", joined)
            # The record stance rides the same channel on both providers.
            self.assertIn("read later, outside this", joined)


class BtwAsideTest(unittest.TestCase):
    """A BTW lookup leaves no trace on the branch.

    It is a side question about the branch, asked whether or not a real turn is
    running. It is answered from the branch's context and written nowhere: not to
    history.jsonl, not to a compaction, not to the internal git. Asides recorded
    before this (they used to be written and hidden) stay hidden from the timeline
    and the prompt.
    """

    def _branch(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        return root, store

    def test_an_aside_turn_records_nothing_and_returns_its_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REAL_QUESTION", extra={"mode": "chat"})
            store.append_history("b1", "assistant", "REAL_ANSWER", extra={"mode": "chat"})
            before = list(store.iter_history("b1"))
            turn_before = ctxgit.internal_git_commit_turn(
                store, kind="test", actor="test", summary="baseline", branch_id="b1"
            )
            head_before = ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_branch_ref("b1"))

            seen: dict[str, str] = {}

            def fake_history_chat(provider, root_, store_, branch_id, user_message, **kwargs):
                seen["prompt_branch"] = branch_id
                seen["message"] = user_message
                return {"assistant": "SIDE_ANSWER"}

            original = ctxgit.call_provider_history_chat
            ctxgit.call_provider_history_chat = fake_history_chat
            try:
                payload = ctxgit.run_history_chat_turn(root, store, "b1", "SIDE_QUESTION", aside=True)
            finally:
                ctxgit.call_provider_history_chat = original

            self.assertEqual(payload["asideAnswer"], "SIDE_ANSWER")
            self.assertNotIn("turnCommit", payload)
            self.assertEqual(seen["message"], "SIDE_QUESTION")
            # Nothing on disk changed: same records, same internal git head.
            self.assertEqual(list(store.iter_history("b1")), before)
            self.assertEqual(
                ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_branch_ref("b1")), head_before
            )
            self.assertEqual(turn_before["commit"], head_before)
            self.assertEqual(list(store.branch_paths("b1").compactions.glob("*.md")), [])

    def test_an_aside_works_with_no_turn_running(self) -> None:
        # Nothing about an aside depends on a job being in flight: the prompt it
        # builds simply has no <running_turn> block.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REAL_QUESTION", extra={"mode": "chat"})
            prompt = ctxgit.build_history_chat_prompt(store, "b1", "SIDE_QUESTION")
            self.assertIn("SIDE_QUESTION", prompt)
            self.assertIn("REAL_QUESTION", prompt)
            self.assertNotIn("<running_turn>", prompt)

    def test_the_api_runs_an_aside_as_its_own_job_that_no_page_adopts(self) -> None:
        # /api/jobs/active is what a reloaded (or second) page uses to re-attach to
        # running turns. A BTW job must not be in that list, or the page would show
        # the branch as busy and turn the composer into Stop for a side question.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REAL_QUESTION", extra={"mode": "chat"})
            before = list(store.iter_history("b1"))
            release = threading.Event()

            def slow_history_chat(provider, root_, store_, branch_id, user_message, **kwargs):
                release.wait(timeout=10)
                return {"assistant": "SIDE_ANSWER"}

            original = ctxgit.call_provider_history_chat
            ctxgit.call_provider_history_chat = slow_history_chat
            handler = ctxgit.make_handler(ctxgit.ProjectState(root), auth_required=False)

            def get(base_url, path):
                with urllib.request.urlopen(f"{base_url}{path}", timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            def post(base_url, path, payload):
                request = urllib.request.Request(
                    f"{base_url}{path}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            try:
                with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    try:
                        started = post(
                            base_url,
                            "/api/info-chat/start",
                            {"branch": "b1", "text": "SIDE_QUESTION", "aside": True},
                        )
                        self.assertEqual(started["mode"], "btw")
                        active = get(base_url, "/api/jobs/active")["jobs"]
                        self.assertEqual([job["id"] for job in active], [])
                        release.set()
                        for _ in range(100):
                            job = get(base_url, f"/api/job?id={started['id']}")
                            if job["status"] != "running":
                                break
                            time.sleep(0.05)
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
            finally:
                ctxgit.call_provider_history_chat = original

            self.assertEqual(job["status"], "done")
            self.assertEqual(job["payload"]["asideAnswer"], "SIDE_ANSWER")
            self.assertEqual(list(store.iter_history("b1")), before)

    def test_an_aside_on_a_sequence_room_asks_about_the_room_instead_of_running_it(self) -> None:
        # Observed on tips_re-challenge: the BTW panel was shut on a sequence room
        # because the API would have answered an aside there by running a round.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.create_branch("b2")
            store.append_history("b1", "user", "SEAT_ONE_TOPIC", extra={"mode": "chat"})
            store.create_sequence_room(["b1", "b2"], "room", "Room", ["", ""], ["info-chat", "info-chat"], 4)
            self.assertTrue(ctxgit.branch_is_sequence_room(store, "room"))
            before = list(store.iter_history("room"))
            calls: dict[str, int] = {"room": 0, "history": 0}

            def no_room_turn(*args, **kwargs):
                calls["room"] += 1
                raise AssertionError("an aside must not run the room")

            def fake_history_chat(provider, root_, store_, branch_id, user_message, **kwargs):
                calls["history"] += 1
                self.assertEqual(branch_id, "room")
                return {"assistant": "ABOUT_THE_ROOM"}

            handler = ctxgit.make_handler(ctxgit.ProjectState(root), auth_required=False)

            def get(base_url, path):
                with urllib.request.urlopen(f"{base_url}{path}", timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            def post(base_url, path, payload):
                request = urllib.request.Request(
                    f"{base_url}{path}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            original_room = ctxgit.run_sequence_room_turn
            original_history = ctxgit.call_provider_history_chat
            ctxgit.run_sequence_room_turn = no_room_turn
            ctxgit.call_provider_history_chat = fake_history_chat
            try:
                with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    try:
                        started = post(
                            base_url,
                            "/api/info-chat/start",
                            {"branch": "room", "text": "WHAT_IS_THIS_ROOM_DOING", "aside": True},
                        )
                        self.assertEqual(started["mode"], "btw")
                        for _ in range(100):
                            job = get(base_url, f"/api/job?id={started['id']}")
                            if job["status"] != "running":
                                break
                            time.sleep(0.05)
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
            finally:
                ctxgit.run_sequence_room_turn = original_room
                ctxgit.call_provider_history_chat = original_history

            self.assertEqual(job["status"], "done", job.get("message"))
            self.assertEqual(job["payload"]["asideAnswer"], "ABOUT_THE_ROOM")
            self.assertEqual(calls, {"room": 0, "history": 1})
            self.assertEqual(list(store.iter_history("room")), before)

    def test_an_old_recorded_aside_stays_hidden_from_the_timeline_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REAL_QUESTION", extra={"mode": "chat"})
            store.append_history("b1", "assistant", "REAL_ANSWER", extra={"mode": "chat"})
            store.append_history("b1", "user", "ASIDE_QUESTION", extra={"mode": "info-chat", "aside": True})
            store.append_history(
                "b1", "assistant", "ASIDE_ANSWER", extra={"mode": "info-chat", "aside": True}
            )

            # Still on disk: the branch keeps a full record.
            raw = [record["text"] for record in store.iter_history("b1")]
            self.assertIn("ASIDE_QUESTION", raw)
            self.assertIn("ASIDE_ANSWER", raw)

            payload = ctxgit.branch_payload(store, "b1")
            shown = [record["text"] for record in payload["history"]]
            self.assertEqual(shown, ["REAL_QUESTION", "REAL_ANSWER"])

            prompt = ctxgit.build_chat_prompt(store, "b1", "next")
            self.assertIn("REAL_QUESTION", prompt)
            self.assertNotIn("ASIDE_QUESTION", prompt)
            self.assertNotIn("ASIDE_ANSWER", prompt)

    def test_the_info_chat_prompt_hides_it_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REAL_QUESTION", extra={"mode": "chat"})
            store.append_history("b1", "user", "ASIDE_QUESTION", extra={"aside": True})
            prompt = ctxgit.build_history_chat_prompt(store, "b1", "next")
            self.assertIn("REAL_QUESTION", prompt)
            self.assertNotIn("ASIDE_QUESTION", prompt)

    def test_an_ordinary_info_chat_turn_is_untouched(self) -> None:
        # Only BTW marks asides; a normal Info chat turn stays in the thread.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "INFO_QUESTION", extra={"mode": "info-chat"})
            payload = ctxgit.branch_payload(store, "b1")
            self.assertIn("INFO_QUESTION", [record["text"] for record in payload["history"]])


class RunningTurnVisibilityTest(unittest.TestCase):
    """A side question has to know what it was asked alongside.

    Observed on muse_for_1shot_gen: asked "지금 뭐하고 있냐, 브랜치 돌잖아" while a
    real turn was working, the answer was "돌고 있는 건 이 대화 턴 하나다". It was not
    wrong to conclude that — the request in flight has no answer in history yet, and
    what the turn is doing lives in the job record, which no prompt had ever read.
    """

    def _branch(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        return root, store

    def _job(self, root: Path, job_id: str, **fields) -> None:
        jobs = root / "contexts" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        ctxgit.dump_json(jobs / f"{job_id}.json", {"id": job_id, **fields})

    def test_the_prompt_carries_the_request_and_the_latest_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "REBUILD_THE_DECK", extra={"mode": "chat", "turnId": "t1"})
            self._job(
                root,
                "20260823T130500000000Z",
                branch="b1",
                mode="chat",
                status="running",
                createdAt="2026-08-23T13:05:00Z",
                events=[{"message": "Using tool: Bash · pdf build", "createdAt": "2026-08-23T13:06:00Z"}],
            )

            prompt = ctxgit.build_history_chat_prompt(store, "b1", "지금 뭐하고 있어?")
            self.assertIn("<running_turn>", prompt)
            self.assertIn("REBUILD_THE_DECK", prompt)
            self.assertIn("Using tool: Bash", prompt)
            self.assertIn("It cannot hear you and it is not finished", prompt)

    def test_an_answered_turn_is_not_reported_as_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "OLD_REQUEST", extra={"mode": "chat", "turnId": "t1"})
            store.append_history("b1", "assistant", "OLD_ANSWER", extra={"mode": "chat", "turnId": "t1"})
            self._job(
                root,
                "20260823T130500000000Z",
                branch="b1",
                mode="chat",
                status="done",
                createdAt="2026-08-23T13:05:00Z",
            )
            prompt = ctxgit.build_history_chat_prompt(store, "b1", "뭐 하고 있어?")
            self.assertNotIn("<running_turn>", prompt)

    def test_side_questions_are_not_reported_as_the_running_turn(self) -> None:
        # Otherwise a BTW lookup answers "what is running?" with itself, which is
        # the same non-answer in a new costume.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            for mode in ("btw", "info-chat", "context-chat"):
                self._job(
                    root,
                    f"20260823T1305000000{len(mode):02d}Z",
                    branch="b1",
                    mode=mode,
                    status="running",
                    createdAt="2026-08-23T13:05:00Z",
                )
            prompt = ctxgit.build_history_chat_prompt(store, "b1", "뭐 하고 있어?")
            self.assertNotIn("<running_turn>", prompt)

    def test_another_branch_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.create_branch("b2")
            self._job(
                root,
                "20260823T130500000000Z",
                branch="b2",
                mode="chat",
                status="running",
                createdAt="2026-08-23T13:05:00Z",
            )
            prompt = ctxgit.build_history_chat_prompt(store, "b1", "뭐 하고 있어?")
            self.assertNotIn("<running_turn>", prompt)


class ClaudeSessionFlagTest(unittest.TestCase):
    """The first turn opens a session id; later turns resume it."""

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        ctxgit.write_provider_config(root, {"provider": "claude"})
        return root, store

    def _capture(self, root, store):
        seen: list[list[str]] = []
        original = ctxgit.subprocess.run

        def fake_run(cmd, **_kwargs):
            if "auth" in cmd and "status" in cmd:
                return FakeCompleted(stdout="Logged in")
            seen.append(cmd)
            return FakeCompleted(
                stdout=structured_result({"assistant": "ok", "artifacts": [], "approvalRequests": []})
            )

        ctxgit.subprocess.run = fake_run
        try:
            ctxgit.call_claude_chat(root, store, "b1", "hello")
        finally:
            ctxgit.subprocess.run = original
        return seen[0]

    def test_first_turn_opens_a_session_and_the_next_resumes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)

            first = self._capture(root, store)
            self.assertIn("--session-id", first)
            self.assertNotIn("--no-session-persistence", first)
            opened = first[first.index("--session-id") + 1]

            second = self._capture(root, store)
            self.assertIn("--resume", second)
            self.assertEqual(second[second.index("--resume") + 1], opened)

    def test_switching_model_starts_a_separate_session(self) -> None:
        # A session belongs to the model that built it.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            first = self._capture(root, store)
            opened = first[first.index("--session-id") + 1]

            ctxgit.write_provider_config(root, {"provider": "claude", "model": "sonnet"})
            after = self._capture(root, store)
            self.assertIn("--session-id", after, "a new model gets its own session")
            self.assertNotEqual(after[after.index("--session-id") + 1], opened)
