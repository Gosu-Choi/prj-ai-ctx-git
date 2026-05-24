from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
SPEC = importlib.util.spec_from_file_location("ctxgit", MODULE_PATH)
assert SPEC and SPEC.loader
ctxgit = importlib.util.module_from_spec(SPEC)
sys.modules["ctxgit"] = ctxgit
SPEC.loader.exec_module(ctxgit)


class CtxgitTest(unittest.TestCase):
    def test_branch_append_and_merge_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust", title="AI trust")
            store.create_branch("AIdiscipline", title="AI discipline")

            store.append_history("AItrust", "user", "Can I trust an AI assistant?")
            store.append_history("AIdiscipline", "assistant", "Use explicit rituals.")
            view_path = store.write_merge_view(["AItrust", "AIdiscipline"], "trust-discipline")

            self.assertTrue((root / "contexts/branches/AItrust/context.md").exists())
            history = (root / "contexts/branches/AItrust/history.jsonl").read_text()
            self.assertEqual(json.loads(history)["role"], "user")
            view = view_path.read_text()
            self.assertIn("AI trust (`AItrust`)", view)
            self.assertIn("AI discipline (`AIdiscipline`)", view)
            self.assertIn("Executive Summary", view)
            self.assertIn("Comparative Findings", view)

    def test_research_dry_run_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            path = store.add_note(
                "AItrust",
                "Research: test",
                "## Planned Provider\n\nOpenCode research agent",
                kind="research",
            )
            self.assertTrue(path.exists())
            self.assertIn("| Kind | `research` |", path.read_text())

    def test_chat_turn_records_assistant_and_multiple_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.call_codex_chat
            try:
                ctxgit.call_codex_chat = lambda *_args, **_kwargs: {
                    "assistant": "Here is the next step.",
                    "artifacts": [
                        {"kind": "research-note", "title": "Sources", "body": "## Sources\n\n- A"},
                        {"kind": "decision-record", "title": "Decision", "body": "## Decision\n\n- B"},
                    ],
                }
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "What next?")
            finally:
                ctxgit.call_codex_chat = original

            self.assertEqual(payload["history"][-2]["role"], "user")
            self.assertEqual(payload["history"][-1]["role"], "assistant")
            self.assertEqual(len(payload["history"][-1]["artifacts"]), 2)
            artifacts = sorted((root / "contexts/branches/AItrust/artifacts").glob("*.md"))
            self.assertEqual(len(artifacts), 2)

    def test_chat_turn_records_user_before_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.call_codex_chat
            try:
                def fail(*_args, **_kwargs):
                    raise RuntimeError("provider failed")

                ctxgit.call_codex_chat = fail
                with self.assertRaises(RuntimeError):
                    ctxgit.run_chat_turn(root, store, "AItrust", "Preserve this.")
            finally:
                ctxgit.call_codex_chat = original

            history = list(store.iter_history("AItrust"))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["role"], "user")
            self.assertEqual(history[0]["text"], "Preserve this.")

    def test_codex_timeout_uses_configured_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config = ctxgit.load_json(root / ".ctxgit/config.json")
            config["llm"]["codex"]["timeoutSeconds"] = 2
            ctxgit.dump_json(root / ".ctxgit/config.json", config)

            class Completed:
                returncode = 0
                stdout = "Logged in using ChatGPT"
                stderr = ""

            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "login" in cmd:
                        return Completed()
                    raise ctxgit.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

                ctxgit.subprocess.run = fake_run
                with self.assertRaises(ctxgit.ChatTimeoutError) as caught:
                    ctxgit.call_codex_chat(root, store, "AItrust", "Slow request")
            finally:
                ctxgit.subprocess.run = original

            self.assertIn("2 seconds", str(caught.exception))

    def test_write_provider_config_persists_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.codex_login_status
            try:
                ctxgit.codex_login_status = lambda _root: ctxgit.read_llm_config(_root)["codex"]
                ctxgit.write_provider_config(root, {"timeoutSeconds": 123})
            finally:
                ctxgit.codex_login_status = original

            config = ctxgit.load_json(root / ".ctxgit/config.json")
            self.assertEqual(config["llm"]["codex"]["timeoutSeconds"], 123)

    def test_write_provider_config_persists_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.codex_login_status
            try:
                ctxgit.codex_login_status = lambda _root: ctxgit.read_llm_config(_root)["codex"]
                ctxgit.write_provider_config(root, {"webSearch": False})
            finally:
                ctxgit.codex_login_status = original

            config = ctxgit.load_json(root / ".ctxgit/config.json")
            self.assertIs(config["llm"]["codex"]["webSearch"], False)

    def test_llm_config_defaults_web_search_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config_path = root / ".ctxgit/config.json"
            config = ctxgit.load_json(config_path)
            config["llm"]["codex"].pop("webSearch")
            ctxgit.dump_json(config_path, config)

            llm = ctxgit.read_llm_config(root)
            self.assertIs(llm["codex"]["webSearch"], True)

    def test_llm_config_respects_explicit_web_search_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config_path = root / ".ctxgit/config.json"
            config = ctxgit.load_json(config_path)
            config["llm"]["codex"]["webSearch"] = False
            ctxgit.dump_json(config_path, config)

            llm = ctxgit.read_llm_config(root)
            self.assertIs(llm["codex"]["webSearch"], False)

    def test_main_discovers_workspace_root_from_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            nested = root / "contexts" / "branches" / "AItrust"
            original_cwd = Path.cwd()
            try:
                os.chdir(nested)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = ctxgit.main(["list"])
            finally:
                os.chdir(original_cwd)

            self.assertEqual(code, 0)
            self.assertIn("AItrust", output.getvalue())

    def test_project_state_opens_separate_initialized_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            original_recent = ctxgit.RECENT_PROJECTS_PATH
            original_state_dir = ctxgit.USER_STATE_DIR
            try:
                ctxgit.USER_STATE_DIR = root / "user-state"
                ctxgit.RECENT_PROJECTS_PATH = ctxgit.USER_STATE_DIR / "projects.json"
                state = ctxgit.ProjectState(first)
                payload = state.open(str(first), init=True, init_git=True)
                self.assertTrue(payload["initialized"])
                self.assertTrue((first / ".ctxgit" / "config.json").exists())
                self.assertTrue((first / ".git").exists())

                state.open(str(second), init=True, init_git=True)
                self.assertEqual(state.root(), second.resolve())
                self.assertTrue((second / ".ctxgit" / "config.json").exists())
                self.assertTrue((second / ".git").exists())
                self.assertFalse((first / "contexts").samefile(second / "contexts") if (second / "contexts").exists() else True)
            finally:
                ctxgit.RECENT_PROJECTS_PATH = original_recent
                ctxgit.USER_STATE_DIR = original_state_dir

    def test_browse_directories_marks_project_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            ctxgit.ContextStore(child).init()

            payload = ctxgit.browse_directories(str(root))
            entry = next(item for item in payload["entries"] if item["name"] == "child")
            self.assertTrue(entry["initialized"])

    def test_init_command_creates_git_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ctxgit.main(["--root", str(root), "init"])

            self.assertEqual(code, 0)
            self.assertTrue((root / ".git").exists())
            self.assertTrue((root / ".ctxgit" / "config.json").exists())

    def test_invalid_branch_id_exits(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ctxgit.validate_id("../bad", "branch")


if __name__ == "__main__":
    unittest.main()
