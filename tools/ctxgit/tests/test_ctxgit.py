from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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

    def test_delete_history_record_rewrites_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            first = store.append_history("AItrust", "user", "keep")
            second = store.append_history("AItrust", "assistant", "remove")
            third = store.append_history("AItrust", "user", "keep too")

            removed = store.delete_history_record(
                "AItrust",
                1,
                expected_created_at=second["createdAt"],
                expected_role=second["role"],
            )

            records = list(store.iter_history("AItrust"))
            self.assertEqual(removed["text"], "remove")
            self.assertEqual([record["text"] for record in records], ["keep", "keep too"])
            self.assertEqual(records[0]["createdAt"], first["createdAt"])
            self.assertEqual(records[1]["createdAt"], third["createdAt"])

    def test_delete_history_record_rejects_stale_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            store.append_history("AItrust", "user", "keep")

            with self.assertRaises(ValueError):
                store.delete_history_record("AItrust", 0, expected_created_at="stale")

    def test_merge_creates_branch_with_archived_parent_histories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust", title="AI trust")
            store.create_branch("AIdiscipline", title="AI discipline")
            store.append_history("AItrust", "user", "Trust question")
            store.append_history("AIdiscipline", "assistant", "Discipline answer")

            merge_root = store.merge_branches(["AItrust", "AIdiscipline"], "combined")
            self.assertTrue((merge_root / "context.md").exists())
            history = list(store.iter_history("combined"))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["role"], "system")
            self.assertEqual(history[0]["event"], "merge")
            archives = store.list_archives("combined")
            self.assertEqual([item["id"] for item in archives], ["AItrust", "AIdiscipline"])
            archived = store.archive_payload("combined", "AItrust")
            self.assertEqual(archived["history"][0]["text"], "Trust question")

    def test_agent_files_are_project_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()

            self.assertTrue((root / "contexts" / "AGENTS.md").exists())
            self.assertTrue((root / "contexts" / "USER.md").exists())
            self.assertTrue((root / "contexts" / "MEMORY.md").exists())
            self.assertFalse((root / ".ctxgit" / "AGENTS.md").exists())
            self.assertFalse((root / "contexts" / "branches" / "initial" / "AGENTS.md").exists())

    def test_init_imports_starting_workspace_context_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "MEMORY.md").write_text(
                "# Memory\n\n- Prefer citation-heavy research.\n",
                encoding="utf-8",
            )
            (workspace / "AGENTS.md").write_text(
                "# Agent Rules\n\n- Use the existing OpenClaw voice.\n",
                encoding="utf-8",
            )
            memory_dir = workspace / "memory"
            memory_dir.mkdir()
            (memory_dir / "2026-05-25.md").write_text(
                "# Daily Memory\n\nImportant prior work.",
                encoding="utf-8",
            )

            store = ctxgit.ContextStore(root)
            store.init()
            store.init()

            summary = root / "contexts" / "imports" / "workspace-summary.md"
            manifest = root / "contexts" / "imports" / "workspace-import.json"
            self.assertTrue(summary.exists())
            self.assertTrue(manifest.exists())
            self.assertTrue((root / "contexts" / "imports" / "workspace-files" / "AGENTS.md").exists())
            self.assertTrue((root / "contexts" / "imports" / "workspace-files" / "MEMORY.md").exists())
            self.assertIn("Prefer citation-heavy research", summary.read_text(encoding="utf-8"))
            self.assertIn(
                "Use the existing OpenClaw voice",
                (root / "contexts" / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Prefer citation-heavy research",
                (root / "contexts" / "MEMORY.md").read_text(encoding="utf-8"),
            )
            context = (root / "contexts" / "branches" / "initial" / "context.md").read_text(encoding="utf-8")
            self.assertIn("Imported Workspace Digest", context)
            history = list(store.iter_history("initial"))
            imports = [item for item in history if item.get("event") == "workspace-import"]
            self.assertEqual(len(imports), 1)

    def test_clone_branch_copies_content_with_new_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            store.append_history("source", "user", "Keep this")
            store.add_note("source", "Note", "Body")

            store.clone_branch("source", "copy")

            self.assertEqual(list(store.iter_history("copy"))[0]["text"], "Keep this")
            self.assertTrue(any((root / "contexts" / "branches" / "copy" / "notes").glob("*.md")))
            meta = ctxgit.load_json(root / "contexts" / "branches" / "copy" / "branch.json")
            self.assertEqual(meta["id"], "copy")
            self.assertEqual(meta["clonedFrom"], "source")

    def test_rename_branch_updates_title_and_context_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("initial", title="Initial branch")

            store.rename_branch("initial", "Literature Review")

            meta = ctxgit.load_json(root / "contexts" / "branches" / "initial" / "branch.json")
            self.assertEqual(meta["id"], "initial")
            self.assertEqual(meta["title"], "Literature Review")
            context = (root / "contexts" / "branches" / "initial" / "context.md").read_text(encoding="utf-8")
            self.assertTrue(context.startswith("# Literature Review\n"))
            index = (root / "contexts" / "index.md").read_text(encoding="utf-8")
            self.assertIn("| `initial` | Literature Review |", index)

    def test_codex_event_progress_extracts_error_detail(self) -> None:
        event = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "error",
                    "message": "sandbox denied writing outside workspace",
                },
            }
        )

        self.assertIn("sandbox denied", ctxgit.codex_event_progress(event))

    def test_codex_startup_warning_key_groups_noisy_warnings(self) -> None:
        self.assertEqual(
            ctxgit.codex_startup_warning_key(
                "WARN ex_core_plugins::startup_remote_sync: startup remote plugin sync failed"
            ),
            "plugin-sync",
        )
        self.assertEqual(
            ctxgit.codex_startup_warning_key(
                "WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'"
            ),
            "skill-icon",
        )

    def test_env_loads_brave_key_from_repo_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            repo = Path(tmp) / "repo"
            root.mkdir()
            repo.mkdir()
            original_env = os.environ.get("BRAVE_API_KEY")
            original_project_env = dict(ctxgit._PROJECT_ENV_ORIGINAL)
            original_repo_root = ctxgit.TOOL_REPO_ROOT
            try:
                ctxgit.TOOL_REPO_ROOT = repo
                (repo / ".env").write_text('export BRAVE_API_KEY="repo-key"\nIGNORED_KEY=ignored\n', encoding="utf-8")
                os.environ.pop("BRAVE_API_KEY", None)
                ctxgit._PROJECT_ENV_ORIGINAL.clear()

                status = ctxgit.load_project_env(root)

                self.assertEqual(os.environ.get("BRAVE_API_KEY"), "repo-key")
                self.assertEqual(status["sources"]["BRAVE_API_KEY"], "ctxgit repo .env")
                self.assertTrue((repo / ".env.example").exists())
            finally:
                ctxgit.TOOL_REPO_ROOT = original_repo_root
                if original_env is None:
                    os.environ.pop("BRAVE_API_KEY", None)
                else:
                    os.environ["BRAVE_API_KEY"] = original_env
                ctxgit._PROJECT_ENV_ORIGINAL.clear()
                ctxgit._PROJECT_ENV_ORIGINAL.update(original_project_env)

    def test_project_env_can_override_repo_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            repo = Path(tmp) / "repo"
            root.mkdir()
            repo.mkdir()
            (root / ".ctxgit").mkdir()
            original_env = os.environ.get("BRAVE_API_KEY")
            original_project_env = dict(ctxgit._PROJECT_ENV_ORIGINAL)
            original_repo_root = ctxgit.TOOL_REPO_ROOT
            try:
                ctxgit.TOOL_REPO_ROOT = repo
                (repo / ".env").write_text("BRAVE_API_KEY=repo-key\n", encoding="utf-8")
                (root / ".ctxgit" / ".env").write_text("BRAVE_API_KEY=project-key\n", encoding="utf-8")
                os.environ.pop("BRAVE_API_KEY", None)
                ctxgit._PROJECT_ENV_ORIGINAL.clear()

                status = ctxgit.load_project_env(root)

                self.assertEqual(os.environ.get("BRAVE_API_KEY"), "project-key")
                self.assertEqual(status["sources"]["BRAVE_API_KEY"], "project .ctxgit/.env")
            finally:
                ctxgit.TOOL_REPO_ROOT = original_repo_root
                if original_env is None:
                    os.environ.pop("BRAVE_API_KEY", None)
                else:
                    os.environ["BRAVE_API_KEY"] = original_env
                ctxgit._PROJECT_ENV_ORIGINAL.clear()
                ctxgit._PROJECT_ENV_ORIGINAL.update(original_project_env)

    def test_snapshot_does_not_track_project_env_file(self) -> None:
        if not shutil.which("git"):
            self.skipTest("git unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, text=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "ctxgit@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "ctxgit"], cwd=root, check=True)
            store = ctxgit.ContextStore(root)
            store.init()
            (root / ".ctxgit" / ".env").write_text("BRAVE_API_KEY=secret\n", encoding="utf-8")

            ctxgit.run_snapshot(root, "snapshot")

            tracked = subprocess.run(
                ["git", "ls-files", "--", ".ctxgit/.env"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertEqual(tracked.stdout.strip(), "")

    def test_job_store_persists_completed_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            project_state = ctxgit.ProjectState(root)
            jobs = ctxgit.JobStore(project_state)

            started = jobs.create("unit", lambda progress: {"ok": True})
            for _ in range(50):
                snapshot = jobs.snapshot(started["id"])
                if snapshot.get("status") == "done":
                    break
                time.sleep(0.02)

            self.assertEqual(snapshot["status"], "done")
            self.assertTrue((root / "contexts" / "jobs" / f"{started['id']}.json").exists())
            reloaded = ctxgit.JobStore(project_state).snapshot(started["id"])
            self.assertEqual(reloaded["status"], "done")
            self.assertEqual(reloaded["payload"], {"ok": True})

    def test_job_store_marks_persisted_running_job_as_restarted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            project_state = ctxgit.ProjectState(root)
            job_id = "20260525T111339869850Z"
            ctxgit.dump_json(
                root / "contexts" / "jobs" / f"{job_id}.json",
                {
                    "id": job_id,
                    "kind": "chat",
                    "status": "running",
                    "createdAt": ctxgit.utc_now(),
                    "updatedAt": ctxgit.utc_now(),
                    "events": [{"message": "Started", "createdAt": ctxgit.utc_now()}],
                },
            )

            snapshot = ctxgit.JobStore(project_state).snapshot(job_id)

            self.assertEqual(snapshot["status"], "failed")
            self.assertEqual(snapshot["error"], "server_restarted")
            self.assertIn("서버가 재시작", snapshot["message"])

    def test_ingest_source_extracts_text_into_branch_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "paper.txt"
            source.write_text("Important source text.", encoding="utf-8")
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            meta = store.ingest_source("source", source)

            self.assertEqual(meta["status"], "extracted")
            self.assertTrue((root / meta["sourcePath"]).exists())
            self.assertTrue((root / meta["textPath"]).exists())
            payload = ctxgit.branch_payload(store, "source")
            self.assertEqual(len(payload["sources"]), 1)
            bundle = ctxgit.build_context_bundle(store, "source")
            self.assertIn("Important source text.", bundle["sources"])

    def test_history_compaction_preserves_raw_history_and_enters_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            for index in range(12):
                store.append_history("AItrust", "user", f"Message {index}")

            path = store.maybe_compact_history("AItrust", threshold=6, keep_tail=3, use_ai=False)

            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.exists())
            self.assertEqual(len(list(store.iter_history("AItrust"))), 12)
            self.assertIsNone(store.maybe_compact_history("AItrust", threshold=6, keep_tail=3, use_ai=False))
            payload = ctxgit.branch_payload(store, "AItrust")
            self.assertEqual(len(payload["compactions"]), 1)
            bundle = ctxgit.build_context_bundle(store, "AItrust")
            self.assertIn("History Compaction: AItrust", bundle["compactions"])

    def test_history_compaction_uses_ai_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            for index in range(8):
                store.append_history("AItrust", "user", f"Message {index}")
            original = ctxgit.call_codex_history_compaction
            try:
                ctxgit.call_codex_history_compaction = lambda *_args, **_kwargs: (
                    "# History Compaction: AItrust\n\n| Mode | `ai` |\n\n## Durable Memory\n\n- AI summary."
                )
                path = store.maybe_compact_history("AItrust", threshold=4, keep_tail=2)
            finally:
                ctxgit.call_codex_history_compaction = original

            self.assertIsNotNone(path)
            assert path is not None
            text = path.read_text(encoding="utf-8")
            self.assertIn("Mode | `ai`", text)
            self.assertIn("AI summary", text)

    def test_remove_branch_deletes_directory_and_recreates_initial_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            store.remove_branch("source")

            self.assertFalse((root / "contexts" / "branches" / "source").exists())
            self.assertTrue((root / "contexts" / "branches" / "initial" / "branch.json").exists())

    def test_ensure_initial_branch_adds_initial_even_when_other_branches_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            created = store.ensure_initial_branch()

            self.assertTrue(created)
            self.assertTrue((root / "contexts" / "branches" / "initial" / "branch.json").exists())
            self.assertTrue((root / "contexts" / "branches" / "source" / "branch.json").exists())

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

    def test_research_turn_records_note_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.call_opencode_research
            try:
                ctxgit.call_opencode_research = lambda *_args, **_kwargs: {
                    "command": ["opencode", "run"],
                    "prompt": "research prompt",
                    "result": {"rawText": "## Executive Summary\n\n- Tested research output."},
                }
                payload = ctxgit.run_research_turn(
                    root,
                    store,
                    "AItrust",
                    "Find relevant evidence.",
                    provider="opencode",
                    args=ctxgit.default_research_args("opencode", timeout=1),
                )
            finally:
                ctxgit.call_opencode_research = original

            self.assertEqual(payload["history"][-2]["role"], "user")
            self.assertEqual(payload["history"][-2]["mode"], "research")
            self.assertEqual(payload["history"][-1]["role"], "assistant")
            self.assertEqual(payload["history"][-1]["artifacts"][0]["kind"], "research")
            note_path = root / payload["history"][-1]["artifacts"][0]["path"]
            self.assertTrue(note_path.exists())
            self.assertIn("Tested research output", note_path.read_text(encoding="utf-8"))

    def test_hybrid_research_uses_collected_sources_and_quality_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original_collect = ctxgit.collect_research_sources
            original_synthesis = ctxgit.call_opencode_synthesis
            try:
                ctxgit.collect_research_sources = lambda query, _args: {
                    "query": query,
                    "sources": [
                        ctxgit.research_result(
                            "semantic-scholar",
                            "Paper A",
                            "https://example.test/paper-a",
                            "Evidence about user control.",
                            kind="paper",
                            authors=["A. Author"],
                            year=2025,
                            venue="CHI",
                        )
                    ],
                    "diagnostics": [{"provider": "brave", "warning": "BRAVE_API_KEY not set"}],
                    "metrics": {
                        "sourceCount": 1,
                        "paperCount": 1,
                        "urlCount": 1,
                        "snippetCount": 1,
                        "providers": ["semantic-scholar"],
                    },
                }
                ctxgit.call_opencode_synthesis = lambda *_args, **_kwargs: {
                    "command": ["opencode", "run"],
                    "prompt": "synthesis prompt",
                    "result": {"rawText": "## Answer\n\nPaper A supports the point [S1]."},
                }

                payload = ctxgit.run_research_turn(
                    root,
                    store,
                    "AItrust",
                    "Find papers about user control.",
                    args=ctxgit.default_research_args("hybrid", timeout=1),
                )
            finally:
                ctxgit.collect_research_sources = original_collect
                ctxgit.call_opencode_synthesis = original_synthesis

            note_path = root / payload["history"][-1]["artifacts"][0]["path"]
            note = note_path.read_text(encoding="utf-8")
            self.assertIn("Search Coverage", note)
            self.assertIn("Quality Warnings", note)
            self.assertIn("Paper A supports the point", note)
            self.assertIn("Collected Source Records", note)

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
                    "approvalRequests": [],
                }
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "What next?")
            finally:
                ctxgit.call_codex_chat = original

            self.assertEqual(payload["history"][-2]["role"], "user")
            self.assertEqual(payload["history"][-1]["role"], "assistant")
            self.assertEqual(len(payload["history"][-1]["artifacts"]), 2)
            artifacts = sorted((root / "contexts/branches/AItrust/artifacts").glob("*.md"))
            self.assertEqual(len(artifacts), 2)

    def test_info_chat_prompt_uses_memory_context_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            ctxgit.write_text(root / "contexts/MEMORY.md", "PROJECT_MEMORY_FACT")
            ctxgit.write_text(root / "contexts/branches/AItrust/context.md", "BRANCH_CONTEXT_FACT")
            store.append_history("AItrust", "user", "HISTORY_FACT")

            prompt = ctxgit.build_history_chat_prompt(store, "AItrust", "What did I say?")

            self.assertIn("HISTORY_FACT", prompt)
            self.assertIn("PROJECT_MEMORY_FACT", prompt)
            self.assertIn("BRANCH_CONTEXT_FACT", prompt)
            self.assertIn("Live web search", prompt)
            self.assertIn("Do not edit files", prompt)

    def test_history_chat_turn_records_assistant_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.call_codex_history_chat
            try:
                ctxgit.call_codex_history_chat = lambda *_args, **_kwargs: {
                    "assistant": "History-only answer.",
                    "artifacts": [{"kind": "ignored", "title": "ignored", "body": "ignored"}],
                    "approvalRequests": [{"path": "ignored", "operation": "ignored", "reason": "ignored"}],
                }
                payload = ctxgit.run_history_chat_turn(root, store, "AItrust", "Use prior chat only.")
            finally:
                ctxgit.call_codex_history_chat = original

            self.assertEqual(payload["history"][-2]["role"], "user")
            self.assertEqual(payload["history"][-1]["role"], "assistant")
            self.assertEqual(payload["history"][-1]["mode"], "info-chat")
            self.assertEqual(payload["history"][-1]["artifacts"], [])
            self.assertEqual(payload["history"][-1]["approvalRequests"], [])

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

    def test_codex_chat_uses_workspace_write_sandbox_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen_commands = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "login" in cmd:
                        return Completed(stdout="Logged in using ChatGPT")
                    seen_commands.append(cmd)
                    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
                    output_path.write_text(
                        json.dumps({"assistant": "ok", "artifacts": [], "approvalRequests": []}),
                        encoding="utf-8",
                    )
                    return Completed()

                ctxgit.subprocess.run = fake_run
                ctxgit.call_codex_chat(root, store, "AItrust", "Edit project files if needed.")
            finally:
                ctxgit.subprocess.run = original

            self.assertTrue(seen_commands)
            command = seen_commands[0]
            self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")

    def test_codex_chat_sends_prompt_via_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            store.append_history("AItrust", "user", "older context")

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen: list[tuple[list[str], dict[str, Any]]] = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "login" in cmd:
                        return Completed(stdout="Logged in using ChatGPT")
                    seen.append((cmd, kwargs))
                    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
                    output_path.write_text(
                        json.dumps({"assistant": "ok", "artifacts": [], "approvalRequests": []}),
                        encoding="utf-8",
                    )
                    return Completed()

                ctxgit.subprocess.run = fake_run
                user_message = "Use Korean and preserve this dash: \u2014"
                ctxgit.call_codex_chat(root, store, "AItrust", user_message)
            finally:
                ctxgit.subprocess.run = original

            self.assertTrue(seen)
            command, kwargs = seen[0]
            self.assertEqual(command[-1], "-")
            self.assertNotIn(user_message, command)
            self.assertIn(user_message, kwargs["input"])
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")

    def test_info_chat_uses_search_and_read_only_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen: list[tuple[list[str], dict[str, Any]]] = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "login" in cmd:
                        return Completed(stdout="Logged in using ChatGPT")
                    seen.append((cmd, kwargs))
                    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
                    output_path.write_text(
                        json.dumps({"assistant": "ok", "artifacts": [], "approvalRequests": []}),
                        encoding="utf-8",
                    )
                    return Completed()

                ctxgit.subprocess.run = fake_run
                ctxgit.call_codex_history_chat(root, store, "AItrust", "Can you check this?")
            finally:
                ctxgit.subprocess.run = original

            self.assertTrue(seen)
            command, kwargs = seen[0]
            self.assertIn("--search", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("Do not edit files", kwargs["input"])

    def test_run_process_with_progress_closes_utf8_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [
                sys.executable,
                "-c",
                "import sys; data = sys.stdin.read(); print('LEN=' + str(len(data)))",
            ]
            completed = ctxgit.run_process_with_progress(
                command,
                root,
                5,
                lambda _message: None,
                stdin_text="Korean stdin with dash \u2014",
            )

            self.assertEqual(completed.returncode, 0)
            self.assertIn("LEN=", completed.stdout)

    def test_codex_chat_adds_only_approved_external_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            approved_file = outside / "note.txt"
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen_commands = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "login" in cmd:
                        return Completed(stdout="Logged in using ChatGPT")
                    seen_commands.append(cmd)
                    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
                    output_path.write_text(
                        json.dumps({"assistant": "ok", "artifacts": [], "approvalRequests": []}),
                        encoding="utf-8",
                    )
                    return Completed()

                ctxgit.subprocess.run = fake_run
                ctxgit.call_codex_chat(
                    root,
                    store,
                    "AItrust",
                    "Edit the approved outside file.",
                    approved_external_paths=[str(approved_file)],
                )
            finally:
                ctxgit.subprocess.run = original

            self.assertTrue(seen_commands)
            command = seen_commands[0]
            self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
            self.assertIn("--add-dir", command)
            self.assertEqual(Path(command[command.index("--add-dir") + 1]), outside.resolve())

    def test_chat_turn_records_external_write_approval_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            root.mkdir()
            outside_file = base / "outside.txt"
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.call_codex_chat
            try:
                ctxgit.call_codex_chat = lambda *_args, **_kwargs: {
                    "assistant": "I need approval before editing outside the project.",
                    "artifacts": [],
                    "approvalRequests": [
                        {
                            "path": str(outside_file),
                            "operation": "edit-file",
                            "reason": "The requested file is outside the opened project.",
                        }
                    ],
                }
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "Edit the outside file.")
            finally:
                ctxgit.call_codex_chat = original

            requests = payload["history"][-1]["approvalRequests"]
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["status"], "pending")
            self.assertEqual(Path(requests[0]["path"]), outside_file.resolve())
            self.assertEqual(payload["approvalStatuses"], {})

    def test_approval_decision_reruns_with_approved_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            root.mkdir()
            outside_file = base / "outside.txt"
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            seen_approved_paths = []
            original = ctxgit.call_codex_chat
            try:
                def fake_chat(*_args, **kwargs):
                    approved = kwargs.get("approved_external_paths") or []
                    if approved:
                        seen_approved_paths.extend(approved)
                        return {"assistant": "Edited after approval.", "artifacts": [], "approvalRequests": []}
                    return {
                        "assistant": "Need approval.",
                        "artifacts": [],
                        "approvalRequests": [
                            {
                                "path": str(outside_file),
                                "operation": "edit-file",
                                "reason": "Outside workspace.",
                            }
                        ],
                    }

                ctxgit.call_codex_chat = fake_chat
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "Edit the outside file.")
                approval_id = payload["history"][-1]["approvalRequests"][0]["id"]
                payload = ctxgit.run_approval_decision(root, store, "AItrust", approval_id, "approved")
            finally:
                ctxgit.call_codex_chat = original

            self.assertEqual(seen_approved_paths, [str(outside_file.resolve())])
            self.assertEqual(payload["approvalStatuses"][approval_id], "approved")
            self.assertEqual(payload["history"][-1]["text"], "Edited after approval.")

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

    def test_write_provider_config_persists_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.codex_login_status
            try:
                ctxgit.codex_login_status = lambda _root: ctxgit.read_llm_config(_root)["codex"]
                ctxgit.write_provider_config(root, {"sandbox": "read-only"})
            finally:
                ctxgit.codex_login_status = original

            config = ctxgit.load_json(root / ".ctxgit/config.json")
            self.assertEqual(config["llm"]["codex"]["sandbox"], "read-only")

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
            state = ctxgit.ProjectState(first)
            payload = state.open(str(first), init=True, init_git=True)
            self.assertTrue(payload["initialized"])
            self.assertNotIn("recent", payload)
            self.assertTrue((first / ".ctxgit" / "config.json").exists())
            self.assertTrue((first / ".git").exists())
            self.assertTrue((first / "contexts" / "branches" / "initial" / "history.jsonl").exists())

            state.open(str(second), init=True, init_git=True)
            self.assertEqual(state.root(), second.resolve())
            self.assertTrue((second / ".ctxgit" / "config.json").exists())
            self.assertTrue((second / ".git").exists())
            self.assertTrue((second / "contexts" / "branches" / "initial" / "history.jsonl").exists())
            self.assertFalse((first / "contexts").samefile(second / "contexts") if (second / "contexts").exists() else True)

    def test_project_state_read_does_not_upgrade_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ctxgit").mkdir()
            ctxgit.dump_json(root / ".ctxgit" / "config.json", {"schemaVersion": 1})
            branch = root / "contexts" / "branches" / "legacy"
            branch.mkdir(parents=True)
            now = ctxgit.utc_now()
            ctxgit.dump_json(
                branch / "branch.json",
                {
                    "schemaVersion": 1,
                    "id": "legacy",
                    "title": "Legacy",
                    "parent": None,
                    "tags": [],
                    "createdAt": now,
                    "updatedAt": now,
                },
            )
            ctxgit.write_text(branch / "context.md", "# Legacy\n")
            ctxgit.write_text(branch / "history.jsonl", "")

            state = ctxgit.ProjectState(root)
            opened_root, store = state.context(require_initialized=True)

            self.assertEqual(opened_root, root.resolve())
            self.assertEqual([item["id"] for item in store.list_branches()], ["legacy"])
            self.assertFalse((root / "contexts" / "AGENTS.md").exists())
            self.assertFalse((root / "contexts" / "branches" / "initial").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_project_open_does_not_upgrade_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ctxgit").mkdir()
            ctxgit.dump_json(root / ".ctxgit" / "config.json", {"schemaVersion": 1})
            (root / "contexts").mkdir()

            state = ctxgit.ProjectState(Path(tmp) / "unused")
            payload = state.open(str(root), init=False)

            self.assertTrue(payload["initialized"])
            self.assertFalse((root / "contexts" / "AGENTS.md").exists())
            self.assertFalse((root / "contexts" / "branches" / "initial").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_serve_root_ignores_tool_repo_without_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".ctxgit").mkdir()
            ctxgit.dump_json(root / ".ctxgit" / "config.json", {"schemaVersion": 1})
            original_cwd = Path.cwd()
            original_tool_repo = ctxgit.TOOL_REPO_ROOT
            try:
                ctxgit.TOOL_REPO_ROOT = root
                os.chdir(root)
                self.assertEqual(ctxgit.resolve_serve_root(None), Path.home().resolve())
                self.assertEqual(ctxgit.resolve_serve_root(str(root)), root)
            finally:
                os.chdir(original_cwd)
                ctxgit.TOOL_REPO_ROOT = original_tool_repo

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
            self.assertTrue((root / "contexts" / "branches" / "initial" / "history.jsonl").exists())

    def test_invalid_branch_id_exits(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ctxgit.validate_id("../bad", "branch")


if __name__ == "__main__":
    unittest.main()
