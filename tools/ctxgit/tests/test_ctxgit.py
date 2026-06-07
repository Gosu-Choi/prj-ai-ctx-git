from __future__ import annotations

import importlib.util
import base64
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
SPEC = importlib.util.spec_from_file_location("ctxgit", MODULE_PATH)
assert SPEC and SPEC.loader
ctxgit = importlib.util.module_from_spec(SPEC)
sys.modules["ctxgit"] = ctxgit
SPEC.loader.exec_module(ctxgit)


class CtxgitTest(unittest.TestCase):
    def test_new_turn_id_uses_timestamp_code(self) -> None:
        turn_id = ctxgit.new_turn_id()

        self.assertRegex(turn_id, r"^turn_\d{8}T\d{6}\d{6}Z$")

    def test_branch_append_and_merge_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust", title="AI trust")
            store.create_branch("AIdiscipline", title="AI discipline")

            record = store.append_history("AItrust", "user", "Can I trust an AI assistant?")
            store.append_history("AIdiscipline", "assistant", "Use explicit rituals.")
            view_path = store.write_merge_view(["AItrust", "AIdiscipline"], "trust-discipline")

            self.assertTrue(record["id"].startswith("msg_"))
            self.assertTrue((root / "contexts/branches/AItrust/context.md").exists())
            history = (root / "contexts/branches/AItrust/history.jsonl").read_text()
            self.assertEqual(json.loads(history)["role"], "user")
            view = view_path.read_text()
            self.assertIn("AI trust (`AItrust`)", view)
            self.assertIn("AI discipline (`AIdiscipline`)", view)
            self.assertIn("Executive Summary", view)
            self.assertIn("Comparative Findings", view)

    def test_list_branches_orders_by_last_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.create_branch("beta")
            store.create_branch("empty")
            store.append_history(
                "alpha",
                "user",
                "Older user message",
                extra={"createdAt": "2026-01-01T00:00:00Z"},
            )
            store.append_history(
                "beta",
                "user",
                "Newer user message",
                extra={"createdAt": "2026-01-03T00:00:00Z"},
            )
            store.append_history(
                "alpha",
                "assistant",
                "Assistant reply after the newer user message",
                extra={"createdAt": "2026-01-04T00:00:00Z"},
            )
            store.rename_branch("empty", "Recently touched")

            items = store.list_branches()

            self.assertEqual([item["id"] for item in items], ["beta", "alpha", "empty"])
            self.assertEqual(items[0]["lastUserMessageAt"], "2026-01-03T00:00:00Z")
            self.assertEqual(items[1]["lastMessageAt"], "2026-01-04T00:00:00Z")

    def test_archive_branch_range_writes_branch_and_globalized_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.append_history("alpha", "user", "first")
            store.append_history("alpha", "assistant", "second")
            store.append_history("alpha", "user", "third")

            payload = store.archive_branch_range("alpha", 2, 3)

            self.assertEqual(payload["id"], "alpha_globalized")
            self.assertEqual([record["text"] for record in payload["history"]], ["second", "third"])
            self.assertFalse((root / "contexts" / "branches" / "alpha").exists())
            self.assertTrue((root / "contexts" / "branches" / "archived" / "alpha" / "history.jsonl").exists())
            self.assertFalse((root / "contexts" / "branches" / "archived" / "alpha" / "archived").exists())
            self.assertTrue((root / "contexts" / "globalized" / "alpha_globalized" / "history.jsonl").exists())
            archives = store.list_globalized_archives()
            self.assertEqual([item["id"] for item in archives], ["alpha_globalized"])
            self.assertEqual(archives[0]["rangeStart"], 2)
            self.assertEqual(archives[0]["rangeEnd"], 3)
            self.assertEqual(store.list_branches(), [])
            archived = store.list_archived_branches()
            self.assertEqual([item["id"] for item in archived], ["alpha"])
            branch_meta = ctxgit.load_json(root / "contexts" / "branches" / "archived" / "alpha" / "branch.json")
            self.assertEqual(branch_meta["archivedAs"], "alpha_globalized")

    def test_archive_branch_without_range_hides_branch_without_globalizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.append_history("alpha", "user", "first")

            payload = store.archive_branch("alpha")

            self.assertEqual(payload["id"], "alpha")
            self.assertEqual(payload["mode"], "branch")
            self.assertFalse((root / "contexts" / "branches" / "alpha").exists())
            self.assertTrue((root / "contexts" / "branches" / "archived" / "alpha" / "history.jsonl").exists())
            self.assertEqual(store.list_branches(), [])
            self.assertEqual([item["id"] for item in store.list_archived_branches()], ["alpha"])
            self.assertEqual(store.list_globalized_archives(), [])
            self.assertFalse((root / "contexts" / "globalized" / "alpha_globalized").exists())
            branch_meta = ctxgit.load_json(root / "contexts" / "branches" / "archived" / "alpha" / "branch.json")
            self.assertEqual(branch_meta["archiveMode"], "branch")
            self.assertIn("archivedAt", branch_meta)
            self.assertNotIn("archivedAs", branch_meta)

    def test_legacy_inner_archived_folder_migrates_to_outer_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.append_history("alpha", "user", "first")
            branch_root = root / "contexts" / "branches" / "alpha"
            legacy_root = branch_root / "archived" / "alpha_globalized"
            ctxgit.write_text(legacy_root / "history.jsonl", json.dumps({"role": "user", "text": "first"}) + "\n")
            ctxgit.write_text(legacy_root / "archive.md", "# alpha_globalized\n")
            ctxgit.dump_json(
                legacy_root / "globalized.json",
                {
                    "schemaVersion": 1,
                    "id": "alpha_globalized",
                    "title": "alpha_globalized",
                    "sourceBranch": "alpha",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "rangeStart": 1,
                    "rangeEnd": 1,
                    "messageCount": 1,
                },
            )
            meta = ctxgit.load_json(branch_root / "branch.json")
            meta["archivedAt"] = "2026-01-01T00:00:00Z"
            ctxgit.dump_json(branch_root / "branch.json", meta)

            self.assertEqual(store.list_branches(), [])

            self.assertFalse(branch_root.exists())
            self.assertTrue((root / "contexts" / "branches" / "archived" / "alpha" / "branch.json").exists())
            self.assertFalse((root / "contexts" / "branches" / "archived" / "alpha" / "archived").exists())
            self.assertTrue((root / "contexts" / "globalized" / "alpha_globalized" / "globalized.json").exists())
            self.assertEqual([item["id"] for item in store.list_archived_branches()], ["alpha"])

    def test_server_project_registry_lists_and_resolves_server_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects_root = Path(tmp) / "server-projects"
            alpha = projects_root / "Alpha Project"
            beta = projects_root / "beta"
            ctxgit.ContextStore(alpha).init()
            ctxgit.ContextStore(beta).init()
            registry = ctxgit.ServerProjectRegistry(alpha, projects_root)

            payload = registry.payload(alpha)

            self.assertTrue(payload["enabled"])
            ids = [project["id"] for project in payload["projects"]]
            self.assertIn("alpha-project", ids)
            self.assertIn("beta", ids)
            self.assertEqual(registry.resolve("beta", alpha), beta.resolve())

    def test_worker_job_queue_claim_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            project_state = ctxgit.ProjectState(root)
            jobs = ctxgit.JobStore(project_state, prefer_worker=True)

            queued = jobs.create_worker("chat", {"kind": "chat", "branch": "initial", "text": "hello"}, root=root)
            claimed = jobs.claim_worker_job("local", ["chat"])

            self.assertEqual(claimed["job"]["id"], queued["id"])
            self.assertEqual(jobs.snapshot(queued["id"])["diagnostics"]["state"], "worker-claimed")
            completed = jobs.complete_worker_job(queued["id"], "local", payload={"ok": True})
            self.assertEqual(completed["status"], "done")
            self.assertEqual(completed["payload"], {"ok": True})

    def test_project_snapshot_round_trip_skips_secrets_and_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            ctxgit.ContextStore(source).init()
            (source / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (source / ".ctxgit" / ".env").write_text("SECRET=2\n", encoding="utf-8")
            (source / ".ctxgit" / "auth.json").write_text('{"secret": true}\n', encoding="utf-8")
            write_job = source / "contexts" / "jobs" / "running.json"
            write_job.parent.mkdir(parents=True, exist_ok=True)
            write_job.write_text("{}", encoding="utf-8")
            (source / "notes.md").write_text("sync me\n", encoding="utf-8")

            changed = ctxgit.apply_project_snapshot_zip(target, ctxgit.make_project_snapshot_zip(source))

            self.assertIn("notes.md", changed)
            self.assertTrue((target / "contexts" / "branches" / "initial" / "branch.json").exists())
            self.assertFalse((target / ".env").exists())
            self.assertFalse((target / ".ctxgit" / ".env").exists())
            self.assertFalse((target / ".ctxgit" / "auth.json").exists())
            self.assertFalse((target / "contexts" / "jobs" / "running.json").exists())

    def test_project_file_browser_uploads_and_previews_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()

            uploaded = ctxgit.upload_project_files(
                root,
                "uploads",
                [
                    {
                        "path": "notes/hello.txt",
                        "contentBase64": base64.b64encode(b"hello server").decode("ascii"),
                    }
                ],
            )

            self.assertEqual(uploaded[0]["path"], "uploads/notes/hello.txt")
            listing = ctxgit.project_files_payload(root, "uploads")
            self.assertEqual(listing["entries"][0]["name"], "notes")
            preview = ctxgit.project_file_text_payload(root, "uploads/notes/hello.txt")
            self.assertEqual(preview["text"], "hello server")

    def test_project_file_upload_rejects_escape_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()

            with self.assertRaises(ValueError):
                ctxgit.upload_project_files(
                    root,
                    "",
                    [
                        {
                            "path": "../outside.txt",
                            "contentBase64": base64.b64encode(b"nope").decode("ascii"),
                        }
                    ],
                )
            with self.assertRaises(ValueError):
                ctxgit.project_files_payload(root, "../")

    def test_project_file_chunk_upload_appends_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()

            first = ctxgit.upload_project_file_chunk(
                root,
                "uploads",
                "notes/large.txt",
                base64.b64encode(b"hello ").decode("ascii"),
                0,
                12,
            )
            second = ctxgit.upload_project_file_chunk(
                root,
                "uploads",
                "notes/large.txt",
                base64.b64encode(b"server").decode("ascii"),
                6,
                12,
                last_chunk=True,
            )

            self.assertFalse(first["complete"])
            self.assertTrue(second["complete"])
            self.assertEqual((root / "uploads" / "notes" / "large.txt").read_text(encoding="utf-8"), "hello server")

    def test_project_file_chunk_upload_rejects_existing_file_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            target = root / "uploads" / "same.txt"
            target.parent.mkdir(parents=True)
            target.write_text("old", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                ctxgit.upload_project_file_chunk(
                    root,
                    "uploads",
                    "same.txt",
                    base64.b64encode(b"new").decode("ascii"),
                    0,
                    3,
                    last_chunk=True,
                )
            result = ctxgit.upload_project_file_chunk(
                root,
                "uploads",
                "same.txt",
                base64.b64encode(b"new").decode("ascii"),
                0,
                3,
                overwrite=True,
                last_chunk=True,
            )

            self.assertTrue(result["complete"])
            self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_auth_store_first_signup_login_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = ctxgit.AuthStore(root)
            previous = os.environ.pop("CTXGIT_ALLOW_SIGNUP", None)
            try:

                self.assertTrue(auth.registration_open())
                user = auth.create_user("Admin_User", "correct horse battery staple")

                self.assertEqual(user["username"], "admin_user")
                self.assertEqual(user["role"], "admin")
                self.assertEqual(user["provider"], "local")
                self.assertFalse(auth.registration_open())
                self.assertIsNone(auth.verify_user("admin_user", "wrong password"))
                self.assertEqual(auth.verify_user("admin_user", "correct horse battery staple")["username"], "admin_user")

                token = auth.create_session("admin_user")
                self.assertEqual(auth.session_user(token)["username"], "admin_user")
                auth.destroy_session(token)
                self.assertIsNone(auth.session_user(token))
            finally:
                if previous is not None:
                    os.environ["CTXGIT_ALLOW_SIGNUP"] = previous

    def test_auth_store_blocks_second_signup_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = ctxgit.AuthStore(root)
            previous = os.environ.pop("CTXGIT_ALLOW_SIGNUP", None)
            try:
                auth.create_user("first", "password one")

                with self.assertRaises(ValueError):
                    auth.create_user("second", "password two")
            finally:
                if previous is not None:
                    os.environ["CTXGIT_ALLOW_SIGNUP"] = previous

    def test_no_auth_handler_allows_project_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            project_state = ctxgit.ProjectState(root)
            handler = ctxgit.make_handler(project_state, auth_required=False)

            with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with urllib.request.urlopen(f"{base_url}/api/auth/status", timeout=5) as response:
                        auth = json.loads(response.read().decode("utf-8"))
                    with urllib.request.urlopen(f"{base_url}/api/project", timeout=5) as response:
                        project_status = response.status
                        project = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

            self.assertFalse(auth["enabled"])
            self.assertTrue(auth["authenticated"])
            self.assertEqual(project_status, 200)
            self.assertEqual(project["path"], str(root.resolve()))

    def test_serve_defaults_to_no_auth_with_auth_opt_in(self) -> None:
        parser = ctxgit.build_parser()

        default_args = parser.parse_args(["serve"])
        auth_args = parser.parse_args(["serve", "--auth"])
        no_auth_args = parser.parse_args(["serve", "--no-auth"])

        self.assertFalse(default_args.auth_required)
        self.assertTrue(auth_args.auth_required)
        self.assertFalse(no_auth_args.auth_required)

    def test_internal_git_commits_turn_to_branch_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.append_history("initial", "user", "hello")
            self.assertIn(".ctxgit/git/", (root / ".gitignore").read_text())

            turn = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="test turn",
                branch_id="initial",
            )

            self.assertTrue(turn["commit"])
            self.assertEqual(ctxgit.internal_git_rev_parse(root, "refs/ctxgit/branches/initial"), turn["commit"])
            status = ctxgit.internal_git_status_payload(root)
            self.assertEqual(status["dirtyCount"], 0)
            self.assertIn("refs/ctxgit/branches/initial", [item["ref"] for item in status["refs"]])

    def test_internal_git_merge_commit_uses_source_branch_parents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.create_branch("beta")
            store.append_history("alpha", "user", "alpha")
            alpha_turn = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user",
                summary="alpha",
                branch_id="alpha",
            )
            store.append_history("beta", "user", "beta")
            beta_turn = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user",
                summary="beta",
                branch_id="beta",
            )

            store.merge_branches(["alpha", "beta"], "merged")
            merge_turn = ctxgit.internal_git_commit_turn(
                store,
                kind="merge",
                actor="user+agent",
                summary="merge alpha beta",
                branch_id="merged",
            )

            parents = ctxgit.run_internal_git(
                root,
                ["rev-list", "--parents", "-n", "1", merge_turn["commit"]],
                check=True,
            ).stdout.strip().split()
            self.assertEqual(parents[0], merge_turn["commit"])
            self.assertIn(alpha_turn["commit"], parents[1:])
            self.assertIn(beta_turn["commit"], parents[1:])

    def test_branch_graph_simplifies_lineage_to_branch_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.append_history("alpha", "user", "alpha")
            store.fork_branch_at_history("alpha", "beta", 0)
            store.create_branch("gamma")
            store.merge_branches(["beta", "gamma"], "merged", branch_summarizer=lambda _request: "summary")

            graph = store.branch_graph_payload()
            nodes = {node["id"]: node for node in graph["nodes"]}
            edge_kinds = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}

            self.assertIn("branch:alpha", nodes)
            self.assertIn("branch:beta", nodes)
            self.assertIn("branch:merged", nodes)
            self.assertIn(("branch:alpha", "branch:beta", "fork"), edge_kinds)
            self.assertIn(("branch:beta", "branch:merged", "merge"), edge_kinds)
            self.assertIn(("branch:gamma", "branch:merged", "merge"), edge_kinds)
            self.assertFalse(any(str(node["id"]).startswith("turn:") for node in graph["nodes"]))

    def test_branch_graph_treats_fork_from_merged_branch_as_fork(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("alpha")
            store.append_history("alpha", "user", "alpha")
            store.create_branch("beta")
            store.append_history("beta", "user", "beta")
            store.merge_branches(["alpha", "beta"], "merged", branch_summarizer=lambda _request: "summary")

            store.fork_branch_at_history("merged", "forked", 0)
            fork_meta_path = root / "contexts" / "branches" / "forked" / "branch.json"
            fork_meta = ctxgit.load_json(fork_meta_path)
            self.assertNotIn("merge", fork_meta)
            self.assertNotIn("parents", fork_meta)

            # Existing projects may already have inherited merge fields on forks.
            # The graph should still prefer the explicit fork lineage.
            fork_meta["merge"] = {"sourceBranches": ["alpha", "beta"]}
            fork_meta["parents"] = ["alpha", "beta"]
            ctxgit.dump_json(fork_meta_path, fork_meta)

            graph = store.branch_graph_payload()
            edge_kinds = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}

            self.assertIn(("branch:alpha", "branch:merged", "merge"), edge_kinds)
            self.assertIn(("branch:beta", "branch:merged", "merge"), edge_kinds)
            self.assertIn(("branch:merged", "branch:forked", "fork"), edge_kinds)
            self.assertNotIn(("branch:alpha", "branch:forked", "merge"), edge_kinds)
            self.assertNotIn(("branch:beta", "branch:forked", "merge"), edge_kinds)
            self.assertEqual(graph["summary"]["mergeBranches"], 1)

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
            self.assertEqual(history[0]["summaryKind"], "common-prefix-divergence-summary")
            self.assertIn("Trust question", history[0]["text"])
            self.assertIn("Discipline answer", history[0]["text"])
            archives = store.list_archives("combined")
            self.assertEqual([item["id"] for item in archives], ["AItrust", "AIdiscipline"])
            archived = store.archive_payload("combined", "AItrust")
            self.assertEqual(archived["history"][0]["text"], "Trust question")
            context = (merge_root / "context.md").read_text(encoding="utf-8")
            self.assertIn("Merged Conversation Summary", context)
            self.assertIn("Deduplicated Source Context", context)
            chat_prompt = ctxgit.build_chat_prompt(store, "combined", "Use archive if needed.")
            self.assertIn("Merge archives available for this branch", chat_prompt)
            self.assertIn("contexts/branches/combined/archives/AItrust/history.jsonl", chat_prompt)
            self.assertIn("archived chat histories", chat_prompt)
            info_prompt = ctxgit.build_history_chat_prompt(store, "combined", "Use archive if needed.")
            self.assertIn("Merge archives available for this branch", info_prompt)
            self.assertIn("contexts/branches/combined/archives/AIdiscipline/context.md", info_prompt)
            source_prompt = ctxgit.build_history_chat_prompt(store, "AItrust", "No archives here.")
            self.assertNotIn("Merge archives available for this branch", source_prompt)

    def test_empty_archive_directory_does_not_add_archive_prompt_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("plain")
            self.assertTrue((root / "contexts/branches/plain/archives").exists())

            prompt = ctxgit.build_history_chat_prompt(store, "plain", "Anything archived?")

            self.assertNotIn("Merge archives available for this branch", prompt)
            self.assertEqual(store.list_archives("plain"), [])

    def test_merge_keeps_common_prefix_once_and_summarizes_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            first = store.append_history("source", "user", "a")
            second = store.append_history("source", "assistant", "b")
            third = store.append_history("source", "user", "c")
            store.fork_branch_at_history("source", "forked", 2, title="Forked")
            store.append_history("source", "assistant", "d")
            store.append_history("source", "user", "e")
            store.append_history("source", "assistant", "f")
            store.append_history("forked", "assistant", "d prime")
            store.append_history("forked", "user", "e prime")
            store.append_history("forked", "assistant", "f prime")

            store.merge_branches(["source", "forked"], "merged")

            records = list(store.iter_history("merged"))
            self.assertEqual([record["text"] for record in records[:3]], ["a", "b", "c"])
            self.assertEqual([record["id"] for record in records[:3]], [first["id"], second["id"], third["id"]])
            self.assertEqual(len(records), 4)
            self.assertEqual(records[-1]["role"], "system")
            self.assertEqual(records[-1]["commonPrefixCount"], 3)
            self.assertIn("d", records[-1]["text"])
            self.assertIn("d prime", records[-1]["text"])

    def test_run_merge_uses_hidden_parallel_info_chats_for_branch_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            store.append_history("source", "user", "a")
            store.append_history("source", "assistant", "b")
            store.append_history("source", "user", "c")
            store.fork_branch_at_history("source", "forked", 2, title="Forked")
            store.append_history("source", "assistant", "d")
            store.append_history("forked", "assistant", "d prime")
            original = ctxgit.call_codex_history_chat
            prompts: dict[str, str] = {}
            active = 0
            max_active = 0
            lock = threading.Lock()
            try:
                def fake_info_chat(_root, _store, branch_id, user_message, progress=None):
                    nonlocal active, max_active
                    with lock:
                        active += 1
                        max_active = max(max_active, active)
                    try:
                        time.sleep(0.05)
                        prompts[branch_id] = user_message
                        return {
                            "assistant": f"LLM summary for {branch_id}",
                            "artifacts": [],
                            "approvalRequests": [],
                        }
                    finally:
                        with lock:
                            active -= 1

                ctxgit.call_codex_history_chat = fake_info_chat
                payload = ctxgit.run_merge_branches(root, store, ["source", "forked"], "merged")
            finally:
                ctxgit.call_codex_history_chat = original

            self.assertEqual(payload["meta"]["id"], "merged")
            self.assertGreaterEqual(max_active, 2)
            self.assertEqual(set(prompts), {"source", "forked"})
            self.assertIn("Divergent tail to summarize", prompts["source"])
            self.assertIn("Shared prefix context", prompts["forked"])
            self.assertEqual(len(list(store.iter_history("source"))), 4)
            self.assertEqual(len(list(store.iter_history("forked"))), 4)
            records = list(store.iter_history("merged"))
            self.assertEqual([record["text"] for record in records[:3]], ["a", "b", "c"])
            self.assertEqual(records[-1]["role"], "system")
            self.assertIn("브랜치 요약", records[-1]["text"])
            self.assertIn("LLM summary for source", records[-1]["text"])
            self.assertIn("LLM summary for forked", records[-1]["text"])

    def test_merge_deduplicates_context_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("left", title="Left")
            store.create_branch("right", title="Right")
            ctxgit.write_text(
                root / "contexts/branches/left/context.md",
                "# Left\n\nShared context line.\n\nLeft-only context.\n",
            )
            ctxgit.write_text(
                root / "contexts/branches/right/context.md",
                "# Right\n\nShared context line.\n\nRight-only context.\n",
            )
            store.append_history("left", "user", "left tail")
            store.append_history("right", "user", "right tail")

            merge_root = store.merge_branches(["left", "right"], "merged")

            context = (merge_root / "context.md").read_text(encoding="utf-8")
            self.assertEqual(context.count("Shared context line."), 1)
            self.assertIn("Left-only context.", context)
            self.assertIn("Right-only context.", context)

    def test_merge_three_branches_uses_pairwise_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            for branch_id in ["rw1", "rw2", "rw3"]:
                store.create_branch(branch_id)
                store.append_history(branch_id, "user", "shared")
            store.append_history("rw1", "assistant", "rw1 tail")
            store.append_history("rw2", "assistant", "rw2 tail")
            store.append_history("rw3", "assistant", "rw3 tail")

            store.merge_branches(["rw1", "rw2", "rw3"], "merged")

            records = list(store.iter_history("merged"))
            self.assertEqual([record["text"] for record in records[:1]], ["shared"])
            self.assertEqual(len(records), 2)
            self.assertEqual(records[-1]["pairwiseStep"], 2)
            self.assertIn("Pairwise Merge Step 2", records[-1]["text"])
            self.assertIn("rw3 tail", records[-1]["text"])
            context = (root / "contexts/branches/merged/context.md").read_text(encoding="utf-8")
            self.assertIn("Pairwise Merge Step 1", context)
            self.assertIn("Pairwise Merge Step 2", context)

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

    def test_fork_branch_copies_context_and_truncates_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            first = store.append_history("source", "user", "First")
            second = store.append_history("source", "assistant", "Second")
            store.append_history("source", "user", "Third")
            ctxgit.write_text(root / "contexts" / "branches" / "source" / "context.md", "# Source\n\nKeep context.\n")
            store.add_note("source", "Note", "Body")

            store.fork_branch_at_history(
                "source",
                "forked",
                1,
                expected_created_at=second["createdAt"],
                expected_role=second["role"],
            )

            self.assertEqual([item["text"] for item in store.iter_history("forked")], ["First", "Second"])
            self.assertEqual([item["text"] for item in store.iter_history("source")], ["First", "Second", "Third"])
            self.assertEqual(
                (root / "contexts" / "branches" / "forked" / "context.md").read_text(encoding="utf-8"),
                "# Source\n\nKeep context.\n",
            )
            self.assertTrue(any((root / "contexts" / "branches" / "forked" / "notes").glob("*.md")))
            meta = ctxgit.load_json(root / "contexts" / "branches" / "forked" / "branch.json")
            self.assertEqual(meta["id"], "forked")
            self.assertEqual(meta["forkedFrom"], "source")
            self.assertEqual(meta["forkedAtIndex"], 1)
            self.assertEqual(meta["forkedAtCreatedAt"], second["createdAt"])
            self.assertEqual(list(store.iter_history("forked"))[0]["createdAt"], first["createdAt"])

    def test_fork_branch_restores_all_branch_files_from_turn_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            first_turn = "turn_20260101T000000000000Z"
            second_turn = "turn_20260101T000001000000Z"
            first = store.append_history("source", "user", "First", extra={"turnId": first_turn})
            ctxgit.write_text(root / "contexts" / "branches" / "source" / "context.md", "# Source\n\nAt first.\n")
            store.add_note("source", "Old Note", "Old body")
            first_commit = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="first turn",
                branch_id="source",
                turn_id=first_turn,
            )

            store.append_history("source", "assistant", "Second", extra={"turnId": second_turn})
            ctxgit.write_text(root / "contexts" / "branches" / "source" / "context.md", "# Source\n\nCurrent later context.\n")
            store.add_note("source", "New Note", "New body")
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="second turn",
                branch_id="source",
                turn_id=second_turn,
            )

            store.fork_branch_at_history("source", "forked", 0, expected_created_at=first["createdAt"])

            fork_root = root / "contexts" / "branches" / "forked"
            self.assertEqual((fork_root / "context.md").read_text(encoding="utf-8"), "# Source\n\nAt first.\n")
            note_text = "\n".join(path.read_text(encoding="utf-8") for path in (fork_root / "notes").glob("*.md"))
            self.assertIn("Old body", note_text)
            self.assertNotIn("New body", note_text)
            self.assertEqual([item["text"] for item in store.iter_history("forked")], ["First"])
            meta = ctxgit.load_json(fork_root / "branch.json")
            self.assertEqual(meta["forkedFromTurnId"], first_turn)
            self.assertEqual(meta["forkedFromCommit"], first_commit["commit"])
            self.assertEqual(meta["forkedSnapshot"], "internal-git")

    def test_cut_branch_restores_history_and_context_to_turn_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="Source")
            first_turn = "turn_20260101T000000000000Z"
            second_turn = "turn_20260101T000001000000Z"
            first = store.append_history("source", "user", "First", extra={"turnId": first_turn})
            ctxgit.write_text(root / "contexts" / "branches" / "source" / "context.md", "# Source\n\nAt first.\n")
            store.add_note("source", "Old Note", "Old body")
            first_commit = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="first turn",
                branch_id="source",
                turn_id=first_turn,
            )

            store.append_history("source", "assistant", "Second", extra={"turnId": second_turn})
            ctxgit.write_text(root / "contexts" / "branches" / "source" / "context.md", "# Source\n\nLater context.\n")
            store.add_note("source", "New Note", "New body")
            second_commit = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="second turn",
                branch_id="source",
                turn_id=second_turn,
            )

            cut = store.cut_branch_at_history(
                "source",
                0,
                expected_created_at=first["createdAt"],
                expected_role=first["role"],
            )

            branch_root = root / "contexts" / "branches" / "source"
            self.assertEqual([item["text"] for item in store.iter_history("source")], ["First"])
            self.assertEqual((branch_root / "context.md").read_text(encoding="utf-8"), "# Source\n\nAt first.\n")
            note_text = "\n".join(path.read_text(encoding="utf-8") for path in (branch_root / "notes").glob("*.md"))
            self.assertIn("Old body", note_text)
            self.assertNotIn("New body", note_text)
            self.assertEqual(cut["turnId"], first_turn)
            self.assertEqual(cut["commit"], first_commit["commit"])
            self.assertEqual(ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_branch_ref("source")), first_commit["commit"])
            self.assertEqual(ctxgit.internal_git_rev_parse(root, "HEAD"), second_commit["commit"])

    def test_cut_branch_rejects_mid_turn_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")
            turn_id = "turn_20260101T000000000000Z"
            first = store.append_history("source", "user", "Question", extra={"turnId": turn_id})
            store.append_history("source", "assistant", "Answer", extra={"turnId": turn_id})
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="one full turn",
                branch_id="source",
                turn_id=turn_id,
            )

            with self.assertRaises(ValueError):
                store.cut_branch_at_history(
                    "source",
                    0,
                    expected_created_at=first["createdAt"],
                    expected_role=first["role"],
                )

    def test_fork_branch_rejects_stale_history_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")
            store.append_history("source", "user", "First")

            with self.assertRaises(ValueError):
                store.fork_branch_at_history("source", "forked", 0, expected_created_at="stale")

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

    def test_context_chat_payload_uses_top_level_contexts_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust", title="AI trust")
            ctxgit.write_text(root / "contexts" / "index.md", "# Context index\n\nOverall map.")
            store.append_context_history("user", "What is the overall context?")

            payload = ctxgit.context_chat_payload(store)
            prompt = ctxgit.build_context_chat_prompt(store, "Summarize.")

            self.assertTrue((root / "contexts" / "history.jsonl").exists())
            self.assertEqual(payload["meta"]["id"], "contexts")
            self.assertTrue(payload["topLevel"])
            self.assertFalse(payload["archived"])
            self.assertEqual(payload["paths"]["root"], "contexts")
            self.assertEqual(payload["paths"]["history"], "contexts/history.jsonl")
            self.assertEqual(payload["history"][-1]["scope"], "contexts")
            self.assertIn("Overall map", payload["context"])
            self.assertIn("scoped to the `contexts/` directory", prompt)
            self.assertIn("AItrust", prompt)
            self.assertIn("Do not fork branches", prompt)

    def test_context_chat_turn_records_assistant_without_branch_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            original = ctxgit.call_codex_context_chat
            try:
                ctxgit.call_codex_context_chat = lambda *_args, **_kwargs: {
                    "assistant": "Overall context answer.",
                    "artifacts": [{"kind": "ignored", "title": "ignored", "body": "ignored"}],
                    "approvalRequests": [{"path": "ignored", "operation": "ignored", "reason": "ignored"}],
                }
                payload = ctxgit.run_context_chat_turn(root, store, "Use all contexts.")
            finally:
                ctxgit.call_codex_context_chat = original

            self.assertTrue(payload["topLevel"])
            self.assertEqual(payload["history"][-2]["role"], "user")
            self.assertEqual(payload["history"][-2]["scope"], "contexts")
            self.assertEqual(payload["history"][-1]["role"], "assistant")
            self.assertEqual(payload["history"][-1]["mode"], "context-chat")
            self.assertEqual(payload["history"][-1]["artifacts"], [])
            self.assertEqual(payload["history"][-1]["approvalRequests"], [])
            self.assertEqual(payload["turnCommit"]["ref"], ctxgit.ctxgit_action_ref())
            self.assertIn("ctxgit: context-chat", ctxgit.internal_git_log(root, ctxgit.ctxgit_action_ref()))

    def test_context_chat_reset_clears_history_and_commits_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.append_context_history("user", "first")
            store.append_context_history("assistant", "second")

            payload = ctxgit.reset_context_chat_history(store)

            self.assertEqual(payload["history"], [])
            self.assertEqual(payload["reset"]["removedMessages"], 2)
            self.assertEqual((root / "contexts" / "history.jsonl").read_text(encoding="utf-8"), "")
            self.assertEqual(payload["turnCommit"]["ref"], ctxgit.ctxgit_action_ref())
            self.assertIn("ctxgit: context-chat-reset", ctxgit.internal_git_log(root, ctxgit.ctxgit_action_ref()))

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

    def test_info_chat_uses_search_read_only_sandbox_and_allows_reads(self) -> None:
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
            self.assertIn("You may read additional project files", kwargs["input"])
            self.assertIn("archive, and branch context files", kwargs["input"])
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
