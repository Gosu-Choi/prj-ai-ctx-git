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
import urllib.error
import urllib.parse
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
    def test_truncate_middle_respects_small_budget(self) -> None:
        self.assertEqual(ctxgit.truncate_middle("abcdef", 0), "")
        self.assertEqual(ctxgit.truncate_middle("abcdef", 3), "abc")
        self.assertLessEqual(len(ctxgit.truncate_middle("abcdef" * 20, 30)), 30)

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

    def test_branch_resource_chunk_upload_stores_file_without_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            first = ctxgit.upload_branch_source_file_chunk(
                store,
                "source",
                "paper.txt",
                base64.b64encode(b"Important ").decode("ascii"),
                0,
                22,
            )
            second = ctxgit.upload_branch_source_file_chunk(
                store,
                "source",
                "paper.txt",
                base64.b64encode(b"source text.").decode("ascii"),
                10,
                22,
                last_chunk=True,
            )
            payload = ctxgit.finish_branch_source_upload(store, "source", ["paper.txt"])

            self.assertFalse(first["complete"])
            self.assertTrue(second["complete"])
            self.assertEqual(payload["uploadedResources"][0]["path"], "contexts/branches/source/resources/paper.txt")
            self.assertEqual(payload["turnCommit"]["ref"], ctxgit.ctxgit_branch_ref("source"))
            self.assertTrue((root / "contexts/branches/source/resources/paper.txt").exists())
            self.assertFalse((root / "contexts/branches/source/resources/paper.txt.meta.json").exists())
            self.assertEqual(
                (root / "contexts/branches/source/resources/paper.txt").read_text(encoding="utf-8"),
                "Important source text.",
            )
            branch_payload = ctxgit.branch_payload(store, "source")
            self.assertEqual(len(branch_payload["resources"]), 1)
            self.assertEqual(branch_payload["sources"], [])

    def test_branch_resource_upload_accepts_image_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            ctxgit.upload_branch_source_file_chunk(
                store,
                "source",
                "image.png",
                base64.b64encode(b"png").decode("ascii"),
                0,
                3,
                last_chunk=True,
            )
            payload = ctxgit.finish_branch_source_upload(store, "source", ["image.png"])

            self.assertEqual(payload["uploadedResources"][0]["path"], "contexts/branches/source/resources/image.png")
            self.assertTrue((root / "contexts/branches/source/resources/image.png").exists())

    def test_branch_resource_upload_accepts_office_files_without_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            ctxgit.upload_branch_source_file_chunk(
                store,
                "source",
                "deck.pptx",
                base64.b64encode(b"pptx bytes").decode("ascii"),
                0,
                10,
                last_chunk=True,
            )
            payload = ctxgit.finish_branch_source_upload(store, "source", ["deck.pptx"])

            self.assertEqual(payload["uploadedResources"][0]["path"], "contexts/branches/source/resources/deck.pptx")
            self.assertTrue((root / "contexts/branches/source/resources/deck.pptx").exists())
            self.assertEqual(ctxgit.resource_kind_for_path(root / "deck.pptx"), "pptx")
            self.assertFalse((root / "contexts/branches/source/resources/deck.pptx.meta.json").exists())

    def test_branch_resource_upload_accepts_any_extension(self) -> None:
        # No extension allowlist: resources are referenced by path in the prompt,
        # not decoded by type, so any file may be attached.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            for name, blob in (("data.csv", b"a,b\n1,2\n"), ("weird.xyz", b"\x00\x01\xff")):
                ctxgit.upload_branch_source_file_chunk(
                    store,
                    "source",
                    name,
                    base64.b64encode(blob).decode("ascii"),
                    0,
                    len(blob),
                    last_chunk=True,
                )
            payload = ctxgit.finish_branch_source_upload(store, "source", ["data.csv", "weird.xyz"])

            paths = [item["path"] for item in payload["uploadedResources"]]
            self.assertEqual(
                paths,
                [
                    "contexts/branches/source/resources/data.csv",
                    "contexts/branches/source/resources/weird.xyz",
                ],
            )
            self.assertTrue((root / "contexts/branches/source/resources/weird.xyz").exists())
            self.assertEqual(ctxgit.resource_kind_for_path(root / "data.csv"), "csv")
            # Path traversal is still rejected regardless of extension.
            with self.assertRaises(ValueError):
                ctxgit.branch_source_upload_relative_path("../escape.csv")

    def test_sanitize_artifact_extension(self) -> None:
        self.assertEqual(ctxgit.sanitize_artifact_extension(""), "md")
        self.assertEqual(ctxgit.sanitize_artifact_extension(None), "md")
        self.assertEqual(ctxgit.sanitize_artifact_extension("HTML"), "html")
        self.assertEqual(ctxgit.sanitize_artifact_extension(".Json"), "json")
        # Unsafe characters are stripped so the extension can never escape the name.
        self.assertEqual(ctxgit.sanitize_artifact_extension("../evil sh"), "evilsh")

    def test_add_artifact_honors_extension_and_only_wraps_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")

            md_path = store.add_artifact("source", "My Report", "- one", kind="report-draft")
            self.assertTrue(md_path.name.endswith(".md"))
            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("## Artifact Metadata", md_text)
            self.assertIn("- one", md_text)

            html = "<!doctype html><html><body><h1>Hi</h1></body></html>"
            html_path = store.add_artifact("source", "Dashboard HTML", html, kind="report-draft", extension="html")
            self.assertTrue(html_path.name.endswith(".html"))
            # Non-markdown artifacts are written verbatim, with no markdown wrapper.
            self.assertEqual(html_path.read_text(encoding="utf-8"), html + "\n")
            self.assertNotIn("Artifact Metadata", html_path.read_text(encoding="utf-8"))

    def test_humanize_output_text_replaces_typography(self) -> None:
        out = ctxgit.humanize_output_text(
            "A — b – c ― d, x → y ⇒ z ← w ↔ v, wait…, “q” ‘r’, 3×4÷2, a≥b≤c≈d, ±5, ™©®"
        )
        self.assertEqual(
            out,
            'A --- b -- c --- d, x -> y => z <- w <-> v, wait..., "q" \'r\', 3x4/2, a>=b<=c~=d, +/-5, (TM)(c)(R)',
        )

    def test_humanize_output_text_removes_emoji_and_invisibles(self) -> None:
        self.assertEqual(ctxgit.humanize_output_text("done ✅ warn ⚠️"), "done  warn ")
        self.assertEqual(ctxgit.humanize_output_text("a​b﻿c"), "abc")
        self.assertEqual(ctxgit.humanize_output_text("full（x）："), "full(x):")

    def test_humanize_output_text_turns_middle_dots_into_slashes(self) -> None:
        # In Korean the middle dot joins peers, which a person types as a slash.
        self.assertEqual(ctxgit.humanize_output_text("기술·운영"), "기술/운영")
        self.assertEqual(ctxgit.humanize_output_text("패션·뷰티·푸드"), "패션/뷰티/푸드")
        # U+2027 renders identically and shows up in model output too.
        self.assertEqual(ctxgit.humanize_output_text("A‧B"), "A/B")

    def test_humanize_output_text_preserves_bullets(self) -> None:
        # A bullet opens a list item; swapping it for punctuation would break the
        # markdown rather than de-AI the prose.
        self.assertEqual(ctxgit.humanize_output_text("• item ▪ ▶"), "• item ▪ ▶")

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

    def test_die_errors_return_a_real_http_status_and_message(self) -> None:
        # die() raises SystemExit with a *process* exit code of 1. Handlers used to
        # pass that straight through as the HTTP status, emitting "HTTP/1.0 1" and
        # dropping the connection, so every such error looked like a network
        # failure in the browser instead of an error message.
        self.assertEqual(ctxgit.http_status_from_exit(SystemExit(1), 400), 400)
        self.assertEqual(ctxgit.http_status_from_exit(SystemExit(404), 400), 404)
        self.assertEqual(ctxgit.http_status_from_exit(SystemExit(None), 409), 409)
        self.assertEqual(ctxgit.http_status_from_exit(SystemExit("boom"), 400), 400)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            handler = ctxgit.make_handler(ctxgit.ProjectState(root), auth_required=False)
            with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(f"{base_url}/api/branch?id=missing", timeout=5)
                    status = caught.exception.code
                    payload = json.loads(caught.exception.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

            self.assertEqual(status, 404)
            self.assertEqual(payload["error"], "branch_not_found")
            # die()'s message must survive to the client, not just stderr.
            self.assertIn("missing", payload["message"])

    def test_knowledging_api_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")
            project_state = ctxgit.ProjectState(root)
            handler = ctxgit.make_handler(project_state, auth_required=False)
            captured: dict[str, str] = {}

            def fake_provider(provider, provider_root, prompt, **kwargs):
                captured["prompt"] = prompt
                return {"entry": "## Trust Rubric\n\nSTORED_FACT", "summary": "저장 완료"}

            original_provider = ctxgit.call_provider_prompt
            ctxgit.call_provider_prompt = fake_provider

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
                        created = post(base_url, "/api/knowledge/create", {"title": "Trust Rubric"})
                        doc_id = created["document"]["id"]
                        guiding = post(
                            base_url, "/api/branch/guiding", {"branch": "AItrust", "docs": [doc_id]}
                        )
                        appended = post(
                            base_url,
                            "/api/knowledge/append",
                            {
                                "branch": "AItrust",
                                "doc": doc_id,
                                "instruction": "이 기준을 계속 기억해",
                                "source": "SOURCE_MESSAGE_TEXT",
                            },
                        )
                        with urllib.request.urlopen(
                            f"{base_url}/api/knowledge?branch=AItrust", timeout=5
                        ) as response:
                            listed = json.loads(response.read().decode("utf-8"))
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
            finally:
                ctxgit.call_provider_prompt = original_provider

            self.assertEqual(guiding["guiding"], [doc_id])
            self.assertEqual(listed["guiding"], [doc_id])
            self.assertIn("SOURCE_MESSAGE_TEXT", captured["prompt"])
            self.assertIn("이 기준을 계속 기억해", captured["prompt"])
            self.assertEqual(appended["summary"], "저장 완료")
            stored = (root / "contexts/knowledge" / f"{doc_id}.md").read_text()
            self.assertIn("STORED_FACT", stored)
            # The stored entry now reaches the branch prompt without any tool call.
            self.assertIn("STORED_FACT", ctxgit.build_chat_prompt(store, "AItrust", "Continue."))

    def test_choose_directory_api_handles_non_ascii_git_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "한글 프로젝트"
            root.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            project_state = ctxgit.ProjectState(None)
            handler = ctxgit.make_handler(project_state, auth_required=False)
            original_chooser = ctxgit.choose_project_directory
            ctxgit.choose_project_directory = lambda path_value: root.resolve()

            try:
                with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    request = urllib.request.Request(
                        f"{base_url}/api/project/choose-directory",
                        data=json.dumps({"path": ""}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=5) as response:
                            status = response.status
                            payload = json.loads(response.read().decode("utf-8"))
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
            finally:
                ctxgit.choose_project_directory = original_chooser

            self.assertEqual(status, 200)
            self.assertEqual(payload["path"], str(root.resolve()))
            self.assertTrue(payload["project"]["gitInitialized"])

    def test_handler_uses_project_header_for_tab_scoped_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "first"
            second = base / "second"
            first.mkdir()
            second.mkdir()
            first_store = ctxgit.ContextStore(first)
            second_store = ctxgit.ContextStore(second)
            first_store.init()
            second_store.init()
            second_store.create_branch("second_only")
            project_state = ctxgit.ProjectState(first)
            handler = ctxgit.make_handler(project_state, auth_required=False)

            with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                encoded_second = urllib.parse.quote(str(second.resolve()), safe="")
                try:
                    request = urllib.request.Request(
                        f"{base_url}/api/project",
                        headers={"X-Ctxgit-Project": encoded_second},
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        project = json.loads(response.read().decode("utf-8"))

                    request = urllib.request.Request(
                        f"{base_url}/api/branches",
                        headers={"X-Ctxgit-Project": encoded_second},
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        branches = json.loads(response.read().decode("utf-8"))

                    with urllib.request.urlopen(f"{base_url}/api/project", timeout=5) as response:
                        default_project = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

            self.assertEqual(project["path"], str(second.resolve()))
            self.assertEqual(default_project["path"], str(first.resolve()))
            self.assertIn("second_only", [branch["id"] for branch in branches["branches"]])

    def test_info_chat_start_on_sequence_room_routes_to_sequence_runner(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("one")
            store.create_branch("two")
            store.create_sequence_room(
                ["one", "two"], "room", "Room", ["", ""],
                ["info-chat", "info-chat"], 4,
            )
            project_state = ctxgit.ProjectState(root)
            handler = ctxgit.make_handler(project_state, auth_required=False)
            calls: list[dict[str, str]] = []
            original = ctxgit.run_sequence_room_turn

            def fake_sequence_room_turn(_root, fake_store, branch_id, user_message, max_agent_replies=None, run_mode="send", progress=None):
                calls.append({"branch": branch_id, "text": user_message, "runMode": run_mode})
                return ctxgit.branch_payload(fake_store, branch_id)

            ctxgit.run_sequence_room_turn = fake_sequence_room_turn
            try:
                with ctxgit.ReusableThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    try:
                        request = urllib.request.Request(
                            f"{base_url}/api/info-chat/start",
                            data=json.dumps({"branch": "room", "text": "Run the room."}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request, timeout=5) as response:
                            status = response.status
                            payload = json.loads(response.read().decode("utf-8"))
                        for _ in range(30):
                            with urllib.request.urlopen(f"{base_url}/api/job?id={urllib.parse.quote(payload['id'])}", timeout=5) as response:
                                job = json.loads(response.read().decode("utf-8"))
                            if job.get("status") == "done":
                                break
                            time.sleep(0.1)

                        request = urllib.request.Request(
                            f"{base_url}/api/chat/start",
                            data=json.dumps({"branch": "room", "text": "Run the writable room."}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request, timeout=5) as response:
                            chat_status = response.status
                            chat_payload = json.loads(response.read().decode("utf-8"))
                        for _ in range(30):
                            with urllib.request.urlopen(f"{base_url}/api/job?id={urllib.parse.quote(chat_payload['id'])}", timeout=5) as response:
                                job = json.loads(response.read().decode("utf-8"))
                            if job.get("status") == "done":
                                break
                            time.sleep(0.1)
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
            finally:
                ctxgit.run_sequence_room_turn = original

            self.assertEqual(status, 202)
            self.assertEqual(payload["kind"], "sequence-room")
            self.assertEqual(calls[0]["branch"], "room")
            self.assertEqual(calls[0]["runMode"], "info-chat")
            self.assertEqual(chat_status, 202)
            self.assertEqual(chat_payload["kind"], "sequence-room")
            self.assertEqual(calls[1]["branch"], "room")
            self.assertEqual(calls[1]["runMode"], "send")

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
            gitignore = (root / ".gitignore").read_text()
            self.assertIn(".ctxgit/.env", gitignore)
            self.assertNotIn(".ctxgit/git/", gitignore)

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

    def test_revise_history_record_updates_text_and_preserves_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            turn_id = "turn_20260101T000000000000Z"
            original = store.append_history("AItrust", "user", "Original message", extra={"turnId": turn_id})
            original_commit = ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="original turn",
                branch_id="AItrust",
                turn_id=turn_id,
            )
            original_count = int(
                ctxgit.run_internal_git(
                    root,
                    ["rev-list", "--count", ctxgit.ctxgit_branch_ref("AItrust")],
                    check=True,
                ).stdout.strip()
            )
            paths = store.branch_paths("AItrust")
            paths.compactions.mkdir(parents=True, exist_ok=True)
            ctxgit.write_text(paths.compactions / "old.md", "stale compaction")
            meta = ctxgit.load_json(paths.meta)
            meta["lastCompactedHistoryCount"] = 1
            meta["lastCompactionPath"] = "contexts/branches/AItrust/compactions/old.md"
            ctxgit.dump_json(paths.meta, meta)

            revision = store.revise_history_record(
                "AItrust",
                0,
                "Revised message",
                expected_created_at=original["createdAt"],
                expected_role=original["role"],
            )

            records = list(store.iter_history("AItrust"))
            self.assertEqual(records[0]["text"], "Revised message")
            self.assertEqual(records[0]["id"], original["id"])
            self.assertEqual(records[0]["createdAt"], original["createdAt"])
            self.assertNotIn("revisionCount", records[0])
            self.assertNotIn("revisedAt", records[0])
            self.assertEqual(revision["oldHead"], original_commit["commit"])
            self.assertNotEqual(revision["newHead"], original_commit["commit"])
            self.assertEqual(ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_turn_ref(turn_id)), revision["newHead"])
            self.assertEqual(ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_branch_ref("AItrust")), revision["newHead"])
            rewritten_count = int(
                ctxgit.run_internal_git(
                    root,
                    ["rev-list", "--count", ctxgit.ctxgit_branch_ref("AItrust")],
                    check=True,
                ).stdout.strip()
            )
            self.assertEqual(rewritten_count, original_count)
            self.assertEqual(store.list_compactions("AItrust"), [])
            revised_meta = ctxgit.load_json(paths.meta)
            self.assertNotIn("lastCompactedHistoryCount", revised_meta)

    def test_revise_history_record_rejects_stale_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            store.append_history("AItrust", "assistant", "Original message")

            with self.assertRaises(ValueError):
                store.revise_history_record("AItrust", 0, "Revised", expected_role="user")

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

    def test_sequence_room_create_run_update_and_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("writer", title="Writer")
            store.create_branch("critic", title="Critic")
            store.append_history("writer", "user", "draft background")
            store.append_history("critic", "user", "evaluation background")
            ctxgit.write_text(store.branch_paths("writer").context, "# Writer\n\nWrite releases.\n")
            ctxgit.write_text(store.branch_paths("critic").context, "# Critic\n\nEvaluate releases.\n")
            writer_compactions = store.branch_paths("writer").compactions
            writer_compactions.mkdir(parents=True, exist_ok=True)
            ctxgit.write_text(writer_compactions / "writer-summary.md", "Archived writer summary.")

            store.create_sequence_room(
                ["writer", "critic"],
                "room",
                "Press room",
                ["Write and improve.", "Critique and decide when complete."],
                ["send", "info-chat"],
                6,
            )
            payload = ctxgit.branch_payload(store, "room")
            self.assertEqual(payload["meta"]["kind"], "sequence-room")
            self.assertEqual([item["sourceBranch"] for item in payload["sequenceRoom"]["participants"]], ["writer", "critic"])
            self.assertEqual(payload["sequenceRoom"]["stopDecider"], 2)
            self.assertEqual(payload["history"], [])
            store.update_sequence_speaking_order(
                "room",
                [1, 2],
                evaluator_order=2,
                update_evaluator=True,
            )

            replies = iter(
                [
                    {"assistant": "First draft"},
                    {
                        "assistant": "Needs revision",
                        "sequenceEvaluation": {
                            "decision": "continue",
                            "requiredChanges": ["Tighten the opening."],
                            "optionalSuggestions": [],
                            "criteria": [
                                {"name": criterion, "passed": False, "evidence": "Revision remains."}
                                for criterion in ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA
                            ],
                        },
                    },
                    {"assistant": "Improved draft"},
                    {
                        "assistant": "Complete",
                        "sequenceEvaluation": {
                            "decision": "complete",
                            "requiredChanges": [],
                            "optionalSuggestions": [],
                            "criteria": [
                                {"name": criterion, "passed": True, "evidence": "Satisfied."}
                                for criterion in ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA
                            ],
                        },
                    },
                ]
            )
            original_call = ctxgit.call_provider_prompt
            progress_events = []
            ctxgit.call_provider_prompt = lambda *args, **kwargs: next(replies)
            try:
                result = ctxgit.run_sequence_room_turn(
                    root,
                    store,
                    "room",
                    "Create the release",
                    max_agent_replies=8,
                    progress=progress_events.append,
                )
            finally:
                ctxgit.call_provider_prompt = original_call

            history = result["history"]
            self.assertEqual([item["role"] for item in history], ["user", "assistant", "assistant", "assistant", "assistant"])
            self.assertEqual([item["sequenceSpeaker"]["order"] for item in history[1:]], [1, 2, 1, 2])
            self.assertEqual([item["sequenceAccessMode"] for item in history[1:]], ["send", "info-chat", "send", "info-chat"])
            self.assertTrue(result["sequenceRun"]["stopped"])
            self.assertEqual(result["sequenceRun"]["evaluatorRounds"], 2)
            self.assertEqual(history[2]["sequenceEvaluation"]["decision"], "continue")
            self.assertEqual(history[4]["sequenceEvaluation"]["decision"], "complete")
            self.assertEqual(
                [event for event in progress_events if event.startswith("Sequence reply ")],
                [
                    "Sequence reply 1 saved",
                    "Sequence reply 2 saved",
                    "Sequence reply 3 saved",
                    "Sequence reply 4 saved",
                ],
            )

            comparison = store.sequence_participant_comparison("room", 1)
            self.assertIn("Write releases", comparison["snapshot"]["context"])
            self.assertIn("Archived writer summary", comparison["snapshot"]["summaries"][0]["text"])
            self.assertIn("Archived writer summary", comparison["current"]["summaries"][0]["text"])
            ctxgit.write_text(store.branch_paths("writer").context, "# Writer\n\nUpdated source.\n")
            ctxgit.write_text(writer_compactions / "writer-summary.md", "Updated writer summary.")
            changed_comparison = store.sequence_participant_comparison("room", 1)
            self.assertIn("Archived writer summary", changed_comparison["snapshot"]["summaries"][0]["text"])
            self.assertIn("Updated writer summary", changed_comparison["current"]["summaries"][0]["text"])
            store.update_sequence_participant(
                "room",
                1,
                update_snapshot=True,
                system_prompt="New writer role.",
                access_mode="info-chat",
            )
            updated = store.sequence_participant_comparison("room", 1)
            self.assertIn("Updated source", updated["snapshot"]["context"])
            self.assertIn("Updated writer summary", updated["snapshot"]["summaries"][0]["text"])
            self.assertEqual(updated["participant"]["systemPrompt"], "New writer role.")
            self.assertEqual(updated["participant"]["accessMode"], "info-chat")

            graph = store.branch_graph_payload()
            sequence_edges = [edge for edge in graph["edges"] if edge["kind"] == "sequence"]
            self.assertEqual([(edge["source"], edge["target"], edge["label"]) for edge in sequence_edges], [
                ("branch:writer", "branch:room", "sequence 1"),
                ("branch:critic", "branch:room", "sequence 2"),
            ])

    def test_sequence_room_send_writes_in_room_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("writer")
            store.create_branch("critic")
            store.create_sequence_room(
                ["writer", "critic"],
                "room",
                "Room",
                ["Write.", "Critique."],
                ["send", "send"],
                4,
            )
            store.update_sequence_speaking_order("room", [1, 2], evaluator_order=None, update_evaluator=True)
            calls: list[dict[str, object]] = []
            original_call = ctxgit.call_provider_prompt

            def fake_call(*args, **kwargs):
                calls.append({"args": args, "kwargs": kwargs})
                cwd = Path(kwargs["cwd"])
                (cwd / f"agent-{len(calls)}.md").write_text(f"# Agent {len(calls)}\n", encoding="utf-8")
                (cwd / f"agent-{len(calls)}.pdf").write_bytes(f"%PDF-1.4 agent {len(calls)}".encode())
                return {"assistant": f"Agent {len(calls)} wrote in workspace."}

            ctxgit.call_provider_prompt = fake_call
            try:
                result = ctxgit.run_sequence_room_turn(root, store, "room", "Collaborate.", run_mode="send")
            finally:
                ctxgit.call_provider_prompt = original_call

            workspace = root / "contexts" / "branches" / "room" / "workspace"
            # resolve() both sides: on macOS the temp dir is /var/... but the code
            # hands back /private/var/..., and the paths are equal as directories.
            self.assertEqual(
                [Path(call["kwargs"]["cwd"]).resolve() for call in calls],
                [workspace.resolve(), workspace.resolve()],
            )
            self.assertTrue((workspace / "agent-1.md").exists())
            self.assertTrue((workspace / "agent-2.md").exists())
            self.assertFalse((root / "contexts" / "branches" / "writer" / "agent-1.md").exists())
            self.assertIn("Never create, edit, move, or delete files in the source branch directory.", calls[0]["args"][2])
            self.assertIn("contexts/branches/room/workspace", calls[0]["args"][2])
            artifacts = result["history"][1]["artifacts"]
            self.assertIn(
                {
                    "kind": "created-pdf",
                    "title": "agent-1.pdf",
                    "path": "contexts/branches/room/workspace/agent-1.pdf",
                },
                artifacts,
            )
            # The markdown it also wrote is not named: that is the churn the list
            # used to drown in.
            self.assertEqual([item for item in artifacts if item["path"].endswith(".md")], [])

    def test_sequence_evaluation_defaults_to_continue_when_invalid_or_changes_remain(self) -> None:
        criteria = list(ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA)
        invalid, valid = ctxgit.normalize_sequence_evaluation(None, criteria)
        self.assertFalse(valid)
        self.assertEqual(invalid["decision"], "continue")
        self.assertTrue(invalid["requiredChanges"])

        contradictory, valid = ctxgit.normalize_sequence_evaluation(
            {
                "decision": "complete",
                "requiredChanges": ["One more required revision."],
                "optionalSuggestions": [],
                "criteria": [
                    {"name": criterion, "passed": True, "evidence": "Looks good."}
                    for criterion in criteria
                ],
            },
            criteria,
        )
        self.assertTrue(valid)
        self.assertEqual(contradictory["decision"], "complete")
        self.assertTrue(contradictory["requiredChanges"])
        self.assertFalse(
            ctxgit.sequence_evaluation_allows_stop(
                contradictory,
                valid=valid,
                evaluator_rounds=2,
                minimum_evaluator_rounds=2,
                acceptance_criteria=criteria,
            )
        )

        complete = {
            "decision": "complete",
            "requiredChanges": [],
            "optionalSuggestions": [],
            "criteria": [
                {"name": criterion, "passed": True, "evidence": "Satisfied."}
                for criterion in criteria
            ],
        }
        self.assertFalse(
            ctxgit.sequence_evaluation_allows_stop(
                complete,
                valid=True,
                evaluator_rounds=1,
                minimum_evaluator_rounds=2,
                acceptance_criteria=criteria,
            )
        )
        self.assertTrue(
            ctxgit.sequence_evaluation_allows_stop(
                complete,
                valid=True,
                evaluator_rounds=2,
                minimum_evaluator_rounds=2,
                acceptance_criteria=criteria,
            )
        )

    def test_sequence_room_supports_multiple_agents_and_custom_speaking_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            for branch_id in ("writer", "critic", "legal"):
                store.create_branch(branch_id, title=branch_id.title())

            store.create_sequence_room(
                ["writer", "critic", "legal"],
                "room",
                "Multi-agent room",
                ["Write.", "Critique.", "Check legal language."],
                ["info-chat", "info-chat", "info-chat"],
                4,
            )
            config = store.update_sequence_speaking_order(
                "room",
                [3, 1],
                evaluator_order=3,
                update_evaluator=True,
            )
            self.assertEqual(config["speakingOrder"], [3, 1])
            self.assertEqual(config["stopDecider"], 3)

            replies = iter(
                [
                    {
                        "assistant": "Legal review",
                        "sequenceEvaluation": {
                            "decision": "continue",
                            "requiredChanges": ["Revise disclaimer."],
                            "optionalSuggestions": [],
                            "criteria": [
                                {"name": criterion, "passed": False, "evidence": "Work remains."}
                                for criterion in ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA
                            ],
                        },
                    },
                    {"assistant": "Writer revision"},
                    {
                        "assistant": "Legal review again",
                        "sequenceEvaluation": {
                            "decision": "continue",
                            "requiredChanges": ["One more revision."],
                            "optionalSuggestions": [],
                            "criteria": [
                                {"name": criterion, "passed": False, "evidence": "Work remains."}
                                for criterion in ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA
                            ],
                        },
                    },
                    {"assistant": "Writer revision again"},
                ]
            )
            original_call = ctxgit.call_provider_prompt
            ctxgit.call_provider_prompt = lambda *args, **kwargs: next(replies)
            try:
                result = ctxgit.run_sequence_room_turn(root, store, "room", "Prepare copy", max_agent_replies=4)
            finally:
                ctxgit.call_provider_prompt = original_call

            speakers = [item["sequenceSpeaker"]["order"] for item in result["history"] if item["role"] == "assistant"]
            self.assertEqual(speakers, [3, 1, 3, 1])
            self.assertNotIn(2, speakers)
            self.assertEqual(result["sequenceRun"]["speakingOrder"], [3, 1])

    def test_sequence_room_without_evaluator_runs_one_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            for branch_id in ("one", "two", "three"):
                store.create_branch(branch_id)
            store.create_sequence_room(
                ["one", "two", "three"],
                "room",
                "No evaluator",
                ["", "", ""],
                ["info-chat", "info-chat", "info-chat"],
                20,
            )
            store.update_sequence_speaking_order(
                "room",
                [2, 1],
                evaluator_order=None,
                update_evaluator=True,
            )
            replies = iter([{"assistant": "two"}, {"assistant": "one"}])
            original_call = ctxgit.call_provider_prompt
            ctxgit.call_provider_prompt = lambda *args, **kwargs: next(replies)
            try:
                result = ctxgit.run_sequence_room_turn(root, store, "room", "Go", max_agent_replies=20)
            finally:
                ctxgit.call_provider_prompt = original_call

            speakers = [item["sequenceSpeaker"]["order"] for item in result["history"] if item["role"] == "assistant"]
            self.assertEqual(speakers, [2, 1])
            self.assertIsNone(result["sequenceRun"]["stopDecider"])
            self.assertEqual(result["sequenceRun"]["maxAgentReplies"], 2)
            self.assertIn("one speaking-order cycle", result["sequenceRun"]["stopReason"])

    def test_sequence_prompt_is_budgeted_and_excludes_other_private_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("one")
            store.create_branch("two")
            for index in range(80):
                store.append_history("one", "assistant", f"ONE-{index}-" + ("a" * 1200))
                store.append_history("two", "assistant", f"TWO-{index}-" + ("b" * 1200))
            store.create_sequence_room(
                ["one", "two"], "room", "Room", ["", ""],
                ["info-chat", "info-chat"], 4,
            )
            store.append_history("room", "user", "Current room request")
            participant = store.sequence_room_config("room")["participants"][0]
            prompt = ctxgit.build_sequence_agent_prompt(
                store,
                "room",
                participant,
                reply_index=0,
                maximum=4,
                stop_decider=None,
                evaluator_rounds=0,
                minimum_evaluator_rounds=2,
                acceptance_criteria=ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA,
                pending_required_changes=[],
            )
            self.assertLess(len(prompt), 70000)
            self.assertIn("ONE-79", prompt)
            self.assertNotIn("ONE-0-", prompt)
            self.assertNotIn("TWO-79", prompt)
            self.assertEqual(prompt.count("Current room request"), 1)

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

    def test_contexts_chat_attachments_move_into_a_branch_started_from_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            temp_dir = store.context_chat_temp_dir()
            temp_dir.mkdir(parents=True, exist_ok=True)
            (temp_dir / "deck.md").write_text("deck", encoding="utf-8")
            (temp_dir / "photo.png").write_bytes(b"\x89PNG")
            store.append_context_history("user", "이 파일 봐줘")

            self.assertEqual(
                [f["title"] for f in store.list_context_chat_temp_files()],
                ["deck.md", "photo.png"],
            )
            # The agent gets paths, so it can open them itself.
            prompt = ctxgit.build_context_chat_prompt(store, "뭐가 들었어?")
            self.assertIn("contexts/contexts-chat-temp/deck.md", prompt)

            store.create_branch_from_context_chat("from_chat", title="From chat")

            self.assertEqual(
                [r["title"] for r in store.list_resources("from_chat")],
                ["deck.md", "photo.png"],
            )
            # Moved, not copied: nothing is left for the next Reset to wipe.
            self.assertEqual(store.list_context_chat_temp_files(), [])

    def test_contexts_chat_reset_clears_attachments_with_the_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            temp_dir = store.context_chat_temp_dir()
            temp_dir.mkdir(parents=True, exist_ok=True)
            (temp_dir / "scratch.txt").write_text("x", encoding="utf-8")
            store.append_context_history("user", "hello")

            messages, files = store.reset_context_history()

            self.assertEqual((messages, files), (1, 1))
            self.assertEqual(store.list_context_chat_temp_files(), [])
            self.assertEqual(list(store.iter_context_history()), [])

    def test_contexts_chat_attachment_name_clash_keeps_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("target", title="Target")
            resources = root / "contexts" / "branches" / "target" / "resources"
            resources.mkdir(parents=True, exist_ok=True)
            (resources / "deck.md").write_text("existing", encoding="utf-8")
            temp_dir = store.context_chat_temp_dir()
            temp_dir.mkdir(parents=True, exist_ok=True)
            (temp_dir / "deck.md").write_text("incoming", encoding="utf-8")

            moved = store.move_context_chat_temp_into_branch("target")

            # The branch's own file must survive the handoff.
            self.assertEqual((resources / "deck.md").read_text(encoding="utf-8"), "existing")
            self.assertEqual(len(moved), 1)
            self.assertTrue(moved[0].endswith("deck-2.md"))

    def test_fork_starts_in_the_same_folder_as_its_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("source", title="Source")
            for i in range(3):
                store.append_history("source", "user", f"m{i}")
                # Turn commits make the fork restore from an internal-git snapshot,
                # which is the path where the folder used to be lost.
                ctxgit.internal_git_commit_turn(
                    store, kind="chat", actor="user", summary=f"turn {i}", branch_id="source",
                )
            # Folder assigned *after* those snapshots: the restored branch.json
            # predates it, so the fork must read the source's current metadata.
            store.set_branch_folder("source", "Sales")

            store.fork_branch_at_history("source", "forked", 1)
            store.fork_context_at_history("source", "forked_ctx", 1)
            store.clone_branch("source", "cloned")

            for branch in ("forked", "forked_ctx", "cloned"):
                meta = ctxgit.load_json(root / "contexts" / "branches" / branch / "branch.json")
                self.assertEqual(meta.get("folder"), "Sales", branch)
            forked_meta = ctxgit.load_json(root / "contexts" / "branches" / "forked" / "branch.json")
            self.assertEqual(forked_meta.get("forkedSnapshot"), "internal-git")

    def test_fork_of_an_ungrouped_branch_stays_ungrouped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("loose", title="Loose")
            store.append_history("loose", "user", "hello")
            ctxgit.internal_git_commit_turn(
                store, kind="chat", actor="user", summary="turn", branch_id="loose",
            )

            store.fork_branch_at_history("loose", "loose_fork", 0)

            meta = ctxgit.load_json(root / "contexts" / "branches" / "loose_fork" / "branch.json")
            self.assertNotIn("folder", meta)

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
            source_paths = store.branch_paths("source")
            source_paths.compactions.mkdir(parents=True, exist_ok=True)
            ctxgit.write_text(source_paths.compactions / "old-summary.md", "Old conversation summary.")
            source_meta = ctxgit.load_json(source_paths.meta)
            source_meta["lastCompactedHistoryCount"] = 1
            source_meta["lastCompactionPath"] = "contexts/branches/source/compactions/old-summary.md"
            ctxgit.dump_json(source_paths.meta, source_meta)
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
            self.assertEqual(meta["forkedSnapshot"], "internal-git")

    def test_fork_context_restores_branch_files_with_empty_history(self) -> None:
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
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="second turn",
                branch_id="source",
                turn_id=second_turn,
            )

            store.fork_context_at_history(
                "source",
                "context-only",
                0,
                expected_created_at=first["createdAt"],
                expected_role=first["role"],
            )

            fork_root = root / "contexts" / "branches" / "context-only"
            self.assertEqual((fork_root / "context.md").read_text(encoding="utf-8"), "# Source\n\nAt first.\n")
            note_text = "\n".join(path.read_text(encoding="utf-8") for path in (fork_root / "notes").glob("*.md"))
            self.assertIn("Old body", note_text)
            self.assertNotIn("New body", note_text)
            self.assertEqual(list(store.iter_history("context-only")), [])
            self.assertEqual((fork_root / "history.jsonl").read_text(encoding="utf-8"), "")
            self.assertFalse((fork_root / "compactions").exists())
            meta = ctxgit.load_json(fork_root / "branch.json")
            self.assertEqual(meta["forkedFrom"], "source")
            self.assertEqual(meta["forkedAtIndex"], 0)
            self.assertTrue(meta["forkedContextOnly"])
            self.assertNotIn("lastCompactedHistoryCount", meta)
            self.assertNotIn("lastCompactionPath", meta)

    def test_fork_context_reads_non_ascii_history_from_internal_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source", title="한글 브랜치")
            turn_id = "turn_20260101T000000000000Z"
            message = store.append_history(
                "source",
                "assistant",
                "한글 메시지와 문맥입니다.",
                extra={"turnId": turn_id},
            )
            ctxgit.write_text(
                root / "contexts" / "branches" / "source" / "context.md",
                "# 한글 문맥\n\n복원할 내용입니다.\n",
            )
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="한글 turn",
                branch_id="source",
                turn_id=turn_id,
            )

            store.fork_context_at_history(
                "source",
                "forked",
                0,
                expected_created_at=message["createdAt"],
                expected_role=message["role"],
            )

            fork_root = root / "contexts" / "branches" / "forked"
            self.assertEqual(
                (fork_root / "context.md").read_text(encoding="utf-8"),
                "# 한글 문맥\n\n복원할 내용입니다.\n",
            )
            self.assertEqual(list(store.iter_history("forked")), [])

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

    def test_cut_branch_preserves_revised_history_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")
            first_turn = "turn_20260101T000000000000Z"
            second_turn = "turn_20260101T000001000000Z"
            first = store.append_history("source", "user", "Original", extra={"turnId": first_turn})
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="first turn",
                branch_id="source",
                turn_id=first_turn,
            )
            store.append_history("source", "assistant", "Later", extra={"turnId": second_turn})
            ctxgit.internal_git_commit_turn(
                store,
                kind="chat",
                actor="user+agent",
                summary="second turn",
                branch_id="source",
                turn_id=second_turn,
            )
            store.revise_history_record(
                "source",
                0,
                "Revised",
                expected_created_at=first["createdAt"],
                expected_role=first["role"],
            )

            store.cut_branch_at_history(
                "source",
                0,
                expected_created_at=first["createdAt"],
                expected_role=first["role"],
            )

            records = list(store.iter_history("source"))
            self.assertEqual([record["text"] for record in records], ["Revised"])
            self.assertNotIn("revisionCount", records[0])
            self.assertNotIn("revisedAt", records[0])

    def test_revised_history_survives_fork_and_cut_at_later_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("source")
            records = []
            for index, text in enumerate(["a", "b", "c", "d"], start=1):
                turn_id = f"turn_20260101T00000{index}000000Z"
                record = store.append_history("source", "user", text, extra={"turnId": turn_id})
                ctxgit.write_text(
                    root / "contexts" / "branches" / "source" / "context.md",
                    f"# Source\n\nContext after {text}.\n",
                )
                store.add_note("source", f"note-{text}", f"note after {text}")
                ctxgit.internal_git_commit_turn(
                    store,
                    kind="chat",
                    actor="user+agent",
                    summary=f"turn {text}",
                    branch_id="source",
                    turn_id=turn_id,
                )
                records.append(record)

            store.revise_history_record(
                "source",
                1,
                "b revised",
                expected_created_at=records[1]["createdAt"],
                expected_role=records[1]["role"],
            )
            rewritten_c_commit = ctxgit.internal_git_rev_parse(
                root,
                ctxgit.ctxgit_turn_ref(str(records[2]["turnId"])),
            )

            store.fork_branch_at_history(
                "source",
                "forked",
                2,
                expected_created_at=records[2]["createdAt"],
                expected_role=records[2]["role"],
            )
            fork_records = list(store.iter_history("forked"))
            self.assertEqual([record["text"] for record in fork_records], ["a", "b revised", "c"])
            self.assertNotIn("revisionCount", fork_records[1])
            self.assertNotIn("revisedAt", fork_records[1])
            self.assertEqual(
                (root / "contexts" / "branches" / "forked" / "context.md").read_text(encoding="utf-8"),
                "# Source\n\nContext after c.\n",
            )
            fork_notes = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "contexts" / "branches" / "forked" / "notes").glob("*.md")
            )
            self.assertIn("note after c", fork_notes)
            self.assertNotIn("note after d", fork_notes)

            cut = store.cut_branch_at_history(
                "source",
                2,
                expected_created_at=records[2]["createdAt"],
                expected_role=records[2]["role"],
            )
            cut_records = list(store.iter_history("source"))
            self.assertEqual([record["text"] for record in cut_records], ["a", "b revised", "c"])
            self.assertNotIn("revisionCount", cut_records[1])
            self.assertNotIn("revisedAt", cut_records[1])
            self.assertEqual(cut["commit"], rewritten_c_commit)
            self.assertEqual(
                (root / "contexts" / "branches" / "source" / "context.md").read_text(encoding="utf-8"),
                "# Source\n\nContext after c.\n",
            )
            cut_notes = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "contexts" / "branches" / "source" / "notes").glob("*.md")
            )
            self.assertIn("note after c", cut_notes)
            self.assertNotIn("note after d", cut_notes)
            self.assertEqual(
                ctxgit.internal_git_rev_parse(root, ctxgit.ctxgit_branch_ref("source")),
                rewritten_c_commit,
            )

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

    def test_job_store_cancel_marks_job_and_signals_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init()
            jobs = ctxgit.JobStore(ctxgit.ProjectState(root))

            def work(progress):
                while not progress.cancelled():
                    time.sleep(0.01)
                raise ctxgit.JobCancelledError("canceled")

            started = jobs.create("unit", work)
            canceled = jobs.cancel(started["id"], root=root)
            self.assertEqual(canceled["status"], "canceled")
            self.assertEqual(canceled["error"], "canceled")
            time.sleep(0.05)
            self.assertEqual(jobs.snapshot(started["id"], root=root)["status"], "canceled")

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

    def test_info_chat_prompt_uses_compaction_summary_and_live_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            for index in range(14):
                store.append_history("AItrust", "user", f"old message {index} " + ("x" * 80))

            path = store.maybe_compact_history("AItrust", threshold=300, keep_tail=260, use_ai=False)

            self.assertIsNotNone(path)
            prompt = ctxgit.build_history_chat_prompt(store, "AItrust", "What remains?")
            self.assertIn("Long-history compaction summaries currently injected", prompt)
            self.assertIn("History Compaction: AItrust", prompt)
            self.assertIn("ctxgit replaced", prompt)
            self.assertIn("old message 13", prompt)

    def test_history_compaction_prompt_uses_full_record_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            config = ctxgit.load_json(root / ".ctxgit" / "config.json")
            config["llm"]["provider"] = "claude"
            ctxgit.dump_json(root / ".ctxgit" / "config.json", config)
            sentinel = "FULL_RECORD_MIDDLE_SENTINEL"
            records = [
                {
                    "createdAt": "2026-06-22T00:00:00Z",
                    "role": "user",
                    "text": ("a" * 900) + sentinel + ("b" * 900),
                }
            ]
            captured: dict[str, str] = {}
            original = ctxgit.call_claude_prompt
            try:
                def fake_call_claude_prompt(_root, prompt, **_kwargs):
                    captured["prompt"] = prompt
                    return {"assistant": "summary"}

                ctxgit.call_claude_prompt = fake_call_claude_prompt
                ctxgit.call_provider_history_compaction(root, store, "AItrust", records)
            finally:
                ctxgit.call_claude_prompt = original

            self.assertIn(sentinel, captured["prompt"])
            self.assertNotIn("[... truncated ...]", captured["prompt"])

    def test_sequence_prompt_uses_source_compactions_and_live_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("one")
            store.create_branch("two")
            for index in range(20):
                store.append_history("one", "assistant", f"ONE-{index}-" + ("a" * 140))
                store.append_history("two", "assistant", f"TWO-{index}-" + ("b" * 140))
            store.maybe_compact_history("one", threshold=600, keep_tail=360, use_ai=False)
            store.create_sequence_room(
                ["one", "two"], "room", "Room", ["", ""],
                ["info-chat", "info-chat"], 4,
            )
            store.append_history("room", "user", "Current room request")
            participant = store.sequence_room_config("room")["participants"][0]

            prompt = ctxgit.build_sequence_agent_prompt(
                store,
                "room",
                participant,
                reply_index=0,
                maximum=4,
                stop_decider=None,
                evaluator_rounds=0,
                minimum_evaluator_rounds=2,
                acceptance_criteria=ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA,
                pending_required_changes=[],
            )

            self.assertIn("<source_compactions>", prompt)
            self.assertIn("History Compaction: one", prompt)
            self.assertIn("ctxgit replaced", prompt)
            self.assertIn("ONE-19", prompt)
            self.assertNotIn("TWO-19", prompt)

    def test_sequence_prompt_uses_room_compactions_and_live_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("one")
            store.create_branch("two")
            store.create_sequence_room(
                ["one", "two"], "room", "Room", ["", ""],
                ["info-chat", "info-chat"], 4,
            )
            for index in range(20):
                store.append_history("room", "assistant", f"ROOM-{index}-" + ("r" * 140))
            store.maybe_compact_history("room", threshold=600, keep_tail=360, use_ai=False)
            participant = store.sequence_room_config("room")["participants"][0]

            prompt = ctxgit.build_sequence_agent_prompt(
                store,
                "room",
                participant,
                reply_index=0,
                maximum=4,
                stop_decider=None,
                evaluator_rounds=0,
                minimum_evaluator_rounds=2,
                acceptance_criteria=ctxgit.DEFAULT_SEQUENCE_ACCEPTANCE_CRITERIA,
                pending_required_changes=[],
            )

            self.assertIn("<room_compactions>", prompt)
            self.assertIn("History Compaction: room", prompt)
            self.assertIn("room compactions above", prompt)
            self.assertIn("ROOM-19", prompt)

    def test_sequence_participant_update_copies_existing_source_compaction_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("one")
            store.create_branch("two")
            store.create_sequence_room(
                ["one", "two"], "room", "Room", ["", ""],
                ["info-chat", "info-chat"], 4,
            )
            # Enough material to sit above the retained tail, or compaction will
            # correctly decline and this test has nothing to snapshot.
            for index in range(40):
                store.append_history("one", "assistant", f"UPDATED-ONE-{index}-" + ("u" * 3000))

            original = ctxgit.call_provider_history_compaction
            try:
                ctxgit.call_provider_history_compaction = lambda *_args, **_kwargs: (
                    "# History Compaction: one\n\n## Durable Memory\n\n- Updated source summary."
                )
                store.maybe_compact_history("one")
            finally:
                ctxgit.call_provider_history_compaction = original

            store.update_sequence_participant("room", 1, update_snapshot=True)

            archive_root = store.branch_paths("room").archives / "one"
            archived_meta = ctxgit.load_json(archive_root / "branch.json")
            archived_compaction = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted((archive_root / "compactions").glob("*.md"))
            )
            self.assertGreater(archived_meta["lastCompactedHistoryCount"], 0)
            self.assertIn("Updated source summary", archived_compaction)

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

    def test_guiding_knowledge_is_injected_only_into_branches_that_enabled_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")
            store.create_branch("AIdiscipline")
            document = store.create_knowledge_document("Trust Rubric")
            store.append_knowledge_entry(document["id"], "## Rubric\n\nGUIDING_KNOWLEDGE_FACT")

            store.set_branch_guiding("AItrust", [document["id"]])

            guided_chat = ctxgit.build_chat_prompt(store, "AItrust", "Continue.")
            guided_info = ctxgit.build_history_chat_prompt(store, "AItrust", "Continue.")
            other_chat = ctxgit.build_chat_prompt(store, "AIdiscipline", "Continue.")

            self.assertIn("GUIDING_KNOWLEDGE_FACT", guided_chat)
            self.assertIn("<guiding_knowledge>", guided_chat)
            self.assertIn("GUIDING_KNOWLEDGE_FACT", guided_info)
            self.assertNotIn("GUIDING_KNOWLEDGE_FACT", other_chat)
            # A branch with nothing switched on carries no empty guiding block.
            self.assertNotIn("<guiding_knowledge>", other_chat)
            self.assertEqual(store.branch_guiding_ids("AItrust"), [document["id"]])

    def test_guiding_is_restated_after_the_user_message(self) -> None:
        """The block near the top is tens of thousands of characters from the answer.

        What the model reads last has to point back at it, or the branch's own
        earlier prose in <history> is the most recent style instruction in the
        prompt.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")
            store.create_branch("AIdiscipline")
            document = store.create_knowledge_document("House Style")
            store.append_knowledge_entry(document["id"], "## Rule\n\nGUIDING_KNOWLEDGE_FACT")
            store.set_branch_guiding("AItrust", [document["id"]])

            for prompt in (
                ctxgit.build_chat_prompt(store, "AItrust", "Continue."),
                ctxgit.build_history_chat_prompt(store, "AItrust", "Continue."),
            ):
                self.assertLess(
                    prompt.index("</user_message>"),
                    prompt.index("Before answering, check your draft"),
                )
                # The reminder is a pointer, not a second copy of the documents.
                self.assertEqual(prompt.count("GUIDING_KNOWLEDGE_FACT"), 1)

            # A branch with nothing switched on gets no reminder either.
            self.assertNotIn(
                "Before answering, check your draft",
                ctxgit.build_chat_prompt(store, "AIdiscipline", "Continue."),
            )

    def test_every_prose_prompt_states_the_reading_conditions_last(self) -> None:
        """Shown a chat timeline, a model casts itself as the other party in a live
        conversation and writes for someone who is present to answer back. The
        conditions the answer is actually read under have to be stated after the
        user message, where they are the last thing read, and they do not depend on
        guiding being switched on.

        The assertions stay at that level on purpose. Pinning the behaviors we want
        out of these conditions would put a list of expressions into the program,
        which is the thing this replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")

            for prompt in (
                ctxgit.build_chat_prompt(store, "AItrust", "Continue."),
                ctxgit.build_history_chat_prompt(store, "AItrust", "Continue."),
                ctxgit.build_context_chat_prompt(store, "무슨 브랜치가 있지?"),
            ):
                self.assertIn("committed to this branch and read later", prompt)
                self.assertIn("no further turn is available", prompt)
                self.assertLess(
                    prompt.index("</user_message>"),
                    prompt.index("committed to this branch and read later"),
                )
                # The old framing is what invited the conversational turn.
                self.assertNotIn("answer to show in the chat timeline", prompt)

    def test_guiding_reaches_the_provider_system_prompt(self) -> None:
        """Inside the prompt body guiding is one section of a very long user
        message. Providers that take a system prompt get it there too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")
            document = store.create_knowledge_document("House Style")
            store.append_knowledge_entry(document["id"], "## Rule\n\nGUIDING_KNOWLEDGE_FACT")
            store.set_branch_guiding("AItrust", [document["id"]])

            captured: dict[str, str] = {}
            original = ctxgit.call_claude_prompt
            try:
                def fake_call_claude_prompt(_root, prompt, **kwargs):
                    captured["prompt"] = prompt
                    captured["system_extra"] = kwargs.get("system_extra", "")
                    return {"assistant": "ok"}

                ctxgit.call_claude_prompt = fake_call_claude_prompt
                ctxgit.call_claude_history_chat(root, store, "AItrust", "Continue.")
            finally:
                ctxgit.call_claude_prompt = original

            self.assertIn("GUIDING_KNOWLEDGE_FACT", captured["system_extra"])
            self.assertIn("GUIDING_KNOWLEDGE_FACT", captured["prompt"])

    def test_guiding_system_directive_is_empty_without_guiding(self) -> None:
        self.assertEqual(ctxgit.guiding_system_directive("(none)"), "")
        self.assertEqual(ctxgit.guiding_system_directive(""), "")
        self.assertEqual(ctxgit.guiding_enforcement_parts("(none)"), [])

    def test_history_compaction_prompt_carries_guiding(self) -> None:
        """A compaction outlives the turn that wrote it and is re-injected into
        every later prompt, so one written without guiding contradicts it forever."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            config = ctxgit.load_json(root / ".ctxgit" / "config.json")
            config["llm"]["provider"] = "claude"
            ctxgit.dump_json(root / ".ctxgit" / "config.json", config)
            store.create_branch("AItrust")
            document = store.create_knowledge_document("House Style")
            store.append_knowledge_entry(document["id"], "## Rule\n\nGUIDING_KNOWLEDGE_FACT")
            store.set_branch_guiding("AItrust", [document["id"]])
            records = [{"createdAt": "2026-06-22T00:00:00Z", "role": "user", "text": "hello"}]

            captured: dict[str, str] = {}
            original = ctxgit.call_claude_prompt
            try:
                def fake_call_claude_prompt(_root, prompt, **kwargs):
                    captured["prompt"] = prompt
                    captured["system_extra"] = kwargs.get("system_extra", "")
                    return {"assistant": "summary"}

                ctxgit.call_claude_prompt = fake_call_claude_prompt
                ctxgit.call_provider_history_compaction(root, store, "AItrust", records)
            finally:
                ctxgit.call_claude_prompt = original

            self.assertIn("GUIDING_KNOWLEDGE_FACT", captured["prompt"])
            self.assertIn("GUIDING_KNOWLEDGE_FACT", captured["system_extra"])

    def test_untouched_report_sections_are_dropped_from_prompts(self) -> None:
        """A fresh report is ~1,200 characters of placeholders. Injecting them
        teaches the model nothing and pushes real instructions further away."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")

            untouched = ctxgit.branch_report_for_prompt(store, "AItrust")
            self.assertNotIn("One-paragraph summary of what this branch currently knows.", untouched)
            self.assertNotIn("State the central question this branch is trying to answer.", untouched)
            # Empty is still reported as empty rather than silently hidden.
            self.assertIn("Still at the template default", untouched)
            self.assertIn("Executive Summary", untouched)
            # Real per-branch values survive.
            self.assertIn("Report Metadata", untouched)
            self.assertLess(len(untouched), len(store.context_excerpt("AItrust")))

            paths = store.branch_paths("AItrust")
            filled = ctxgit.read_text(paths.context).replace(
                "- One-paragraph summary of what this branch currently knows.",
                "- FILLED_IN_SUMMARY_SENTINEL",
            )
            ctxgit.write_text(paths.context, filled)
            after = ctxgit.branch_report_for_prompt(store, "AItrust")
            self.assertIn("FILLED_IN_SUMMARY_SENTINEL", after)
            self.assertIn("## Executive Summary", after)
            self.assertNotIn("Executive Summary,", after.split("Still at the template default")[-1])

    def test_guiding_selection_survives_and_drops_deleted_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            store.create_branch("AItrust")
            kept = store.create_knowledge_document("Kept")
            removed = store.create_knowledge_document("Removed")
            store.set_branch_guiding("AItrust", [kept["id"], removed["id"]])

            (root / "contexts/knowledge" / f"{removed['id']}.md").unlink()

            self.assertEqual(store.branch_guiding_ids("AItrust"), [kept["id"]])
            with self.assertRaises(SystemExit):
                store.set_branch_guiding("AItrust", ["does-not-exist"])
            store.set_branch_guiding("AItrust", [])
            meta = json.loads((root / "contexts/branches/AItrust/branch.json").read_text())
            self.assertNotIn("guiding", meta)

    def test_knowledge_append_is_append_only_and_lists_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()
            document = store.create_knowledge_document("Metric Definitions")

            store.append_knowledge_entry(document["id"], "## First\n\nFIRST_ENTRY")
            updated = store.append_knowledge_entry(document["id"], "## Second\n\nSECOND_ENTRY")

            text = (root / "contexts/knowledge" / f"{document['id']}.md").read_text()
            self.assertIn("# Metric Definitions", text)
            self.assertLess(text.index("FIRST_ENTRY"), text.index("SECOND_ENTRY"))
            self.assertEqual(updated["id"], document["id"])
            listed = [item["id"] for item in store.list_knowledge_documents()]
            self.assertIn(document["id"], listed)
            # The folder README documents the feature and must never be injected.
            self.assertNotIn("README", listed)
            with self.assertRaises(SystemExit):
                store.create_knowledge_document("Metric Definitions")

    def test_knowledge_documents_keep_non_ascii_titles_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init()

            first = store.create_knowledge_document("리서치 방법론")
            second = store.create_knowledge_document("지표 정의")

            # The slug cannot carry the Korean title, but the documents must not
            # collide and the title must survive in the file itself.
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["title"], "리서치 방법론")
            self.assertEqual(second["title"], "지표 정의")
            self.assertEqual({item["title"] for item in store.list_knowledge_documents()},
                             {"리서치 방법론", "지표 정의"})
            with self.assertRaises(SystemExit):
                store.create_knowledge_document("리서치 방법론")

    def test_prompts_include_branch_resources_and_current_turn_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            resources = root / "contexts/branches/AItrust/resources"
            resources.mkdir(parents=True, exist_ok=True)
            image = resources / "slide.png"
            image.write_bytes(b"fake png")
            rel = "contexts/branches/AItrust/resources/slide.png"

            chat_prompt = ctxgit.build_chat_prompt(store, "AItrust", "Explain the photo.", resource_paths=[rel])
            info_prompt = ctxgit.build_history_chat_prompt(store, "AItrust", "Explain the photo.", resource_paths=[rel])
            research_prompt = ctxgit.build_research_prompt(store, "AItrust", "Research around this slide.")

            for prompt in (chat_prompt, info_prompt):
                self.assertIn("Current turn attachments", prompt)
                self.assertIn("photos or files they just sent", prompt)
                self.assertIn(rel, prompt)
            self.assertIn("Branch resource files stored as direct attachments", research_prompt)
            self.assertIn(rel, research_prompt)

    def test_chat_prompt_uses_character_budget_without_default_record_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            for index in range(250):
                store.append_history("AItrust", "user", f"MSG-{index:03d}-unique")

            prompt = ctxgit.build_chat_prompt(store, "AItrust", "Continue.")

            self.assertIn("MSG-000-unique", prompt)
            self.assertIn("MSG-249-unique", prompt)
            self.assertNotIn("ctxgit omitted", prompt)

    def test_chat_prompt_respects_history_character_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config = ctxgit.load_json(root / ".ctxgit/config.json")
            config["llm"]["codex"]["historyBudgetCharacters"] = 1200
            config["llm"]["codex"]["historyRecordLimit"] = 0
            ctxgit.dump_json(root / ".ctxgit/config.json", config)
            for index in range(50):
                store.append_history("AItrust", "user", f"MSG-{index:03d}-unique " + ("x" * 80))

            prompt = ctxgit.build_chat_prompt(store, "AItrust", "Continue.")

            self.assertIn("MSG-049-unique", prompt)
            self.assertNotIn("MSG-000-unique", prompt)
            self.assertIn("ctxgit omitted", prompt)

    def test_chat_turn_records_and_passes_current_turn_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            resources = root / "contexts/branches/AItrust/resources"
            resources.mkdir(parents=True, exist_ok=True)
            (resources / "slide.png").write_bytes(b"fake png")
            rel = "contexts/branches/AItrust/resources/slide.png"
            original = ctxgit.call_codex_chat
            captured: dict[str, object] = {}
            try:
                def fake_chat(*_args, **kwargs):
                    captured.update(kwargs)
                    return {"assistant": "I can see the attachment path.", "artifacts": [], "approvalRequests": []}

                ctxgit.call_codex_chat = fake_chat
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "Use the photo.", resource_paths=[rel])
            finally:
                ctxgit.call_codex_chat = original

            self.assertEqual(captured["resource_paths"], [rel])
            self.assertEqual(payload["history"][-2]["resources"], [rel])
            self.assertIn(rel, ctxgit.format_history_record(payload["history"][-2]))

    def test_chat_turn_links_rebuilt_pdfs_and_ignores_markdown_churn(self) -> None:
        """A turn names the PDFs it rebuilt, not the markdown it touched.

        Markdown moves on nearly every turn — branch context, notes, ledgers, the
        index — so listing it buried the answer under paths that told the reader
        nothing. A rebuilt PDF is rare and deliberate.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            existing = root / "deck.pdf"
            existing.write_bytes(b"%PDF-1.4 before")
            original = ctxgit.call_codex_chat
            try:
                def fake_chat(*_args, **_kwargs):
                    existing.write_bytes(b"%PDF-1.4 after, and longer")
                    (root / "report.pdf").write_bytes(b"%PDF-1.4 fresh")
                    (root / "notes.md").write_text("churn\n", encoding="utf-8")
                    return {"assistant": "Rebuilt the deck.", "artifacts": [], "approvalRequests": []}

                ctxgit.call_codex_chat = fake_chat
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "Rebuild it.")
            finally:
                ctxgit.call_codex_chat = original

            artifacts = payload["history"][-1]["artifacts"]
            self.assertIn({"kind": "created-pdf", "title": "report.pdf", "path": "report.pdf"}, artifacts)
            self.assertIn({"kind": "modified-pdf", "title": "deck.pdf", "path": "deck.pdf"}, artifacts)
            self.assertEqual([item for item in artifacts if item["path"].endswith(".md")], [])

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

    def test_claude_read_only_tools_include_web_without_write_tools(self) -> None:
        tools = ctxgit.claude_tools(writable=False, web_search=True).split(",")
        self.assertIn("WebSearch", tools)
        self.assertIn("WebFetch", tools)
        self.assertNotIn("Edit", tools)
        self.assertNotIn("Write", tools)
        self.assertNotIn("Bash", tools)

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

    def test_write_provider_config_can_select_claude_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            original = ctxgit.provider_status
            ctxgit.provider_status = lambda _root: {
                "ok": True,
                "provider": ctxgit.read_llm_config(_root)["provider"],
            }
            try:
                status = ctxgit.write_provider_config(
                    root,
                    {
                        "provider": "claude",
                        "model": "opus",
                        "timeoutSeconds": 321,
                        "webSearch": True,
                        "sandbox": "read-only",
                    },
                )
            finally:
                ctxgit.provider_status = original
            config = ctxgit.read_llm_config(root)
            self.assertEqual(status["provider"], "claude")
            self.assertEqual(config["provider"], "claude")
            self.assertEqual(config["claude"]["model"], "opus")
            self.assertEqual(config["claude"]["timeoutSeconds"], 321)
            self.assertNotIn("apiKey", config["claude"])

    def test_parse_claude_structured_output(self) -> None:
        parsed = ctxgit.parse_claude_result(
            json.dumps(
                {
                    "type": "result",
                    "structured_output": {
                        "assistant": "Claude answer",
                        "artifacts": [],
                        "approvalRequests": [],
                    },
                }
            )
        )
        self.assertEqual(parsed["assistant"], "Claude answer")
        self.assertEqual(parsed["artifacts"], [])

    def test_claude_structured_output_failure_falls_back_to_relaxed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config = ctxgit.load_json(root / ".ctxgit/config.json")
            config.setdefault("llm", {}).setdefault("claude", {})["strictStructuredOutput"] = True
            ctxgit.dump_json(root / ".ctxgit/config.json", config)

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen: list[tuple[list[str], dict[str, Any]]] = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **kwargs):
                    if "auth" in cmd and "status" in cmd:
                        return Completed(stdout="Logged in using Claude")
                    seen.append((cmd, kwargs))
                    if len(seen) == 1:
                        return Completed(
                            stdout=json.dumps(
                                {
                                    "type": "result",
                                    "subtype": "error_max_structured_output_retries",
                                    "is_error": True,
                                    "errors": [
                                        "Failed to provide valid structured output after 5 attempts"
                                    ],
                                }
                            ),
                            returncode=1,
                        )
                    return Completed(
                        stdout=json.dumps(
                            {
                                "type": "result",
                                "result": json.dumps(
                                    {
                                        "assistant": "fallback answer",
                                        "artifacts": [],
                                        "approvalRequests": [],
                                    }
                                ),
                            }
                        )
                    )

                ctxgit.subprocess.run = fake_run
                result = ctxgit.call_claude_chat(root, store, "AItrust", "Please answer.")
            finally:
                ctxgit.subprocess.run = original

            self.assertEqual(result["assistant"], "fallback answer")
            self.assertIs(result["structuredOutputFallback"], True)
            self.assertEqual(len(seen), 2)
            self.assertIn("--json-schema", seen[0][0])
            self.assertNotIn("--json-schema", seen[1][0])
            self.assertIn("Retry without the CLI JSON schema validator", seen[1][1]["input"])

    def test_claude_chat_uses_strict_schema_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")

            class Completed:
                def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            seen: list[list[str]] = []
            original = ctxgit.subprocess.run
            try:
                def fake_run(cmd, **_kwargs):
                    if "auth" in cmd and "status" in cmd:
                        return Completed(stdout="Logged in using Claude")
                    seen.append(cmd)
                    return Completed(
                        stdout=json.dumps(
                            {
                                "type": "result",
                                "result": json.dumps(
                                    {"assistant": "ok", "artifacts": [], "approvalRequests": []}
                                ),
                            }
                        )
                    )

                ctxgit.subprocess.run = fake_run
                result = ctxgit.call_claude_chat(root, store, "AItrust", "Please answer.")
            finally:
                ctxgit.subprocess.run = original

            self.assertEqual(result["assistant"], "ok")
            self.assertEqual(len(seen), 1)
            self.assertIn("--output-format", seen[0])
            # Streaming output so the UI can surface live intermediate events.
            self.assertIn("stream-json", seen[0])
            # Strict structured output is forced on by default.
            self.assertIn("--json-schema", seen[0])

    def test_provider_models_are_normalized_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            config = ctxgit.load_json(root / ".ctxgit/config.json")
            config["llm"]["codex"]["model"] = ""
            ctxgit.dump_json(root / ".ctxgit/config.json", config)
            self.assertEqual(ctxgit.read_llm_config(root)["codex"]["model"], "gpt-5.6-sol")

            original = ctxgit.provider_status
            ctxgit.provider_status = lambda _root: {"ok": True, "provider": "codex"}
            try:
                ctxgit.write_provider_config(root, {"provider": "codex", "model": "gpt-5.6-terra"})
                with self.assertRaises(ValueError):
                    ctxgit.write_provider_config(root, {"provider": "codex", "model": "opus"})
            finally:
                ctxgit.provider_status = original
            self.assertEqual(ctxgit.read_llm_config(root)["codex"]["model"], "gpt-5.6-terra")

    def test_claude_offers_fable_and_the_1m_context_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            offered = [item["id"] for item in ctxgit.LLM_PROVIDER_MODELS["claude"]]
            self.assertEqual(offered[0], "fable")
            self.assertIn("opus[1m]", offered)

            original = ctxgit.provider_status
            ctxgit.provider_status = lambda _root: {"ok": True, "provider": "claude"}
            try:
                for model in offered:
                    ctxgit.write_provider_config(root, {"provider": "claude", "model": model})
                    self.assertEqual(ctxgit.read_llm_config(root)["claude"]["model"], model)
                with self.assertRaises(ValueError):
                    ctxgit.write_provider_config(root, {"provider": "claude", "model": "opus-9"})
            finally:
                ctxgit.provider_status = original

    def test_claude_stage_model_reads_a_role_tier_relative_to_the_selection(self) -> None:
        # Frontier roles follow the project's choice; cheaper roles stay cheap
        # unless the choice itself is cheaper than the role asked for.
        self.assertEqual(ctxgit.claude_stage_model("opus", "fable"), "fable")
        self.assertEqual(ctxgit.claude_stage_model("opus", "opus[1m]"), "opus[1m]")
        self.assertEqual(ctxgit.claude_stage_model("opus", "opus"), "opus")
        self.assertEqual(ctxgit.claude_stage_model("sonnet", "fable"), "sonnet")
        self.assertEqual(ctxgit.claude_stage_model("haiku", "opus"), "haiku")
        self.assertEqual(ctxgit.claude_stage_model("sonnet", "haiku"), "haiku")
        # No role tier: the project's model. No selection: the role's tier.
        self.assertEqual(ctxgit.claude_stage_model("", "fable[1m]"), "fable[1m]")
        self.assertEqual(ctxgit.claude_stage_model("sonnet", ""), "sonnet")
        # A pinned model id on either side is deliberate, so it is left alone.
        self.assertEqual(ctxgit.claude_stage_model("claude-opus-4-5", "fable"), "claude-opus-4-5")
        self.assertEqual(ctxgit.claude_model_tier("Fable[1M]"), "fable")

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
            gitignore = (root / ".gitignore").read_text()
            self.assertIn(".ctxgit/.env", gitignore)
            self.assertNotIn(".ctxgit/git/", gitignore)

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
            gitignore = (root / ".gitignore").read_text()
            self.assertIn(".ctxgit/.env", gitignore)
            self.assertNotIn(".ctxgit/git/", gitignore)

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

    def test_project_payload_handles_non_ascii_git_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "한글 프로젝트"
            root.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            payload = ctxgit.project_payload(root)

            self.assertEqual(payload["path"], str(root.resolve()))
            self.assertTrue(payload["gitInitialized"])

    def test_init_command_does_not_create_git_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ctxgit.main(["--root", str(root), "init"])

            self.assertEqual(code, 0)
            self.assertFalse((root / ".git").exists())
            self.assertTrue((root / ".ctxgit" / "config.json").exists())
            self.assertTrue((root / "contexts" / "branches" / "initial" / "history.jsonl").exists())

    def test_init_command_creates_git_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ctxgit.main(["--root", str(root), "init", "--git"])

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


class CodexThreadLifetimeTest(unittest.TestCase):
    """One Codex thread per turn, not one per branch.

    ctxgit rebuilds the whole context every turn — project instructions, guiding
    knowledge, branch report, budgeted history. A resumed thread already holds all
    of that from every previous turn, so resuming and re-sending stacks the branch
    history N deep by turn N and leaves N copies of the guiding block with the
    newest buried among superseded ones. Claude avoids this with
    `--no-session-persistence`; Codex asks for an ephemeral thread.
    """

    def test_a_resumed_turn_sends_only_what_is_new(self) -> None:
        """Resuming is safe only because the turn stops re-sending the context.

        The first attempt resumed the thread *and* re-sent the whole rebuilt prompt,
        so by turn N the branch history was nested N deep and the current guiding
        block sat among N-1 superseded copies.
        """
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        self.assertIn("thread/resume", source)
        self.assertIn("def build_continuation_prompt(", source)

    def test_a_turn_without_a_progress_channel_takes_codex_exec(self) -> None:
        # Nothing to stream to and nobody to interject, so the app-server
        # handshake buys nothing.
        self.assertIsNone(ctxgit.codex_steerable_progress(None))

        def progress(_message: str) -> None:
            return None

        self.assertIs(ctxgit.codex_steerable_progress(progress), progress)


if __name__ == "__main__":
    unittest.main()


class TrackedOutputTest(unittest.TestCase):
    """What a turn changed, and how much of it is worth reading.

    Markdown was the only tracked format, so a turn that rebuilt a PDF said
    nothing about it. PDFs are signed by size and mtime rather than hashed: a
    project can hold hundreds of megabytes of them and a turn snapshots twice.
    """

    def test_only_pdfs_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deck.pdf").write_bytes(b"%PDF-1.4 first")
            before = ctxgit.tracked_file_snapshot(root)

            (root / "deck.pdf").write_bytes(b"%PDF-1.4 second and longer")
            (root / "report.pdf").write_bytes(b"%PDF-1.4 brand new")
            # Markdown churns on every turn — context, notes, ledgers, the index —
            # and naming all of it buried the answer.
            (root / "note.md").write_text("new", encoding="utf-8")
            (root / "context.md").write_text("changed", encoding="utf-8")
            refs = ctxgit.changed_tracked_file_refs(root, before, ctxgit.tracked_file_snapshot(root))

            by_path = {ref["path"]: ref["kind"] for ref in refs}
            self.assertEqual(by_path.get("deck.pdf"), "modified-pdf")
            self.assertEqual(by_path.get("report.pdf"), "created-pdf")
            self.assertNotIn("note.md", by_path)
            self.assertNotIn("context.md", by_path)

    def test_an_untouched_pdf_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.pdf").write_bytes(b"%PDF-1.4 stable")
            before = ctxgit.tracked_file_snapshot(root)
            self.assertEqual(
                ctxgit.changed_tracked_file_refs(root, before, ctxgit.tracked_file_snapshot(root)), []
            )


class HistoryIndexMappingTest(unittest.TestCase):
    """The index the UI holds and the row in the file stopped being the same thing.

    BTW asides are written to history.jsonl but not shown, so a delete aimed at the
    last visible message pointed a few rows short. The createdAt guard caught it and
    said "record changed before delete; refresh and try again" — which reads like a
    race, so refreshing never helped and the message could not be removed.
    """

    def _branch(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        return root, store

    def test_a_visible_index_maps_past_the_hidden_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "FIRST")
            store.append_history("b1", "user", "ASIDE_A", extra={"aside": True})
            store.append_history("b1", "user", "ASIDE_B", extra={"aside": True})
            store.append_history("b1", "user", "SECOND")

            visible = [record["text"] for record in ctxgit.branch_payload(store, "b1")["history"]]
            self.assertEqual(visible, ["FIRST", "SECOND"])
            # "SECOND" is index 1 on screen and index 3 in the file.
            self.assertEqual(ctxgit.raw_history_index(store, "b1", 1), 3)
            self.assertEqual(ctxgit.raw_history_index(store, "b1", 0), 0)

    def test_deleting_the_last_visible_message_removes_that_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            store.append_history("b1", "user", "KEEP")
            store.append_history("b1", "user", "ASIDE", extra={"aside": True})
            store.append_history("b1", "user", "REMOVE_ME")

            shown = ctxgit.branch_payload(store, "b1")["history"]
            target = len(shown) - 1
            removed = store.delete_history_record(
                "b1",
                ctxgit.raw_history_index(store, "b1", target),
                expected_created_at=shown[target]["createdAt"],
                expected_role="user",
            )
            self.assertEqual(removed["text"], "REMOVE_ME")
            remaining = [record["text"] for record in store.iter_history("b1")]
            self.assertEqual(remaining, ["KEEP", "ASIDE"])

    def test_a_branch_with_no_asides_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._branch(tmp)
            for text in ("a", "b", "c"):
                store.append_history("b1", "user", text)
            for index in range(3):
                self.assertEqual(ctxgit.raw_history_index(store, "b1", index), index)


class CompactionHysteresisTest(unittest.TestCase):
    """Compaction has to leave a gap behind it.

    The trigger measured everything uncompacted, but a compaction only folds what
    sits above the tail it keeps. With the threshold and the tail budget both at
    40k, a branch that compacted once came back holding a 40k tail — already at the
    threshold — so the next single message crossed it again. From then on every
    turn paid for an extra model call that folded one or two records, which is what
    tripled info-chat turn times on the busy branches.
    """

    def _busy_branch(self, store, branch: str, records: int, size: int) -> None:
        store.create_branch(branch)
        for index in range(records):
            store.append_history(branch, "user" if index % 2 == 0 else "assistant", "x" * size)

    def test_a_branch_sitting_on_a_full_tail_does_not_recompact_every_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            # ~52k of history: over the 40k trigger, but only ~17k of it sits above
            # the 40k tail — not enough to be worth folding.
            self._busy_branch(store, "b1", records=13, size=4000)
            self.assertGreater(
                ctxgit.history_records_char_count(list(store.iter_history("b1"))),
                ctxgit.DEFAULT_COMPACTION_THRESHOLD,
            )
            self.assertIsNone(store.maybe_compact_history("b1", use_ai=False))

    def test_enough_material_above_the_tail_still_compacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            self._busy_branch(store, "b1", records=40, size=4000)
            self.assertIsNotNone(store.maybe_compact_history("b1", use_ai=False))

    def test_compacting_twice_needs_a_second_run_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            self._busy_branch(store, "b1", records=40, size=4000)
            self.assertIsNotNone(store.maybe_compact_history("b1", use_ai=False))
            # One more message is not a reason to fold again.
            store.append_history("b1", "user", "x" * 4000)
            self.assertIsNone(store.maybe_compact_history("b1", use_ai=False))


class BranchProviderOverrideTest(unittest.TestCase):
    """One branch can sit on a different model without moving the project.

    Provider settings were project-wide, so trying a heavier model on one branch
    switched every branch onto it — and switching back was the only way out.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("plain")
        store.create_branch("heavy")
        return root, store

    def test_an_override_moves_only_its_own_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            store.set_branch_llm("heavy", {"provider": "claude", "model": "fable"})

            self.assertEqual(ctxgit.read_llm_config(root, "heavy")["provider"], "claude")
            self.assertEqual(ctxgit.read_llm_config(root, "heavy")["claude"]["model"], "fable")
            # The project and every other branch are untouched.
            self.assertEqual(ctxgit.read_llm_config(root)["claude"]["model"], "opus")
            self.assertEqual(ctxgit.read_llm_config(root, "plain")["claude"]["model"], "opus")

    def test_clearing_an_override_follows_the_project_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            store.set_branch_llm("heavy", {"provider": "claude", "model": "fable"})
            store.set_branch_llm("heavy", {"provider": None, "model": None})

            self.assertEqual(store.set_branch_llm("heavy", {}), {})
            self.assertEqual(
                ctxgit.read_llm_config(root, "heavy")["claude"]["model"],
                ctxgit.read_llm_config(root)["claude"]["model"],
            )
            # Following, not frozen: a later project change reaches the branch.
            ctxgit.provider_status = lambda _root: {"ok": True, "provider": "claude"}
            ctxgit.write_provider_config(root, {"provider": "claude", "model": "sonnet"})
            self.assertEqual(ctxgit.read_llm_config(root, "heavy")["claude"]["model"], "sonnet")

    def test_a_model_is_checked_against_the_provider_offering_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            with self.assertRaises(ValueError):
                store.set_branch_llm("heavy", {"provider": "claude", "model": "gpt-5.6-sol"})
            with self.assertRaises(ValueError):
                store.set_branch_llm("heavy", {"provider": "nope"})

    def test_settings_land_on_the_provider_that_will_answer(self) -> None:
        # A timeout pinned for a Claude branch must not reach the project's Codex.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            store.set_branch_llm("heavy", {"provider": "claude", "timeoutSeconds": 120})
            resolved = ctxgit.read_llm_config(root, "heavy")
            self.assertEqual(resolved["claude"]["timeoutSeconds"], 120)
            self.assertNotEqual(resolved["codex"]["timeoutSeconds"], 120)


class BranchProviderAuthorityTest(unittest.TestCase):
    """A pinned branch decides, even when the request names a provider.

    The UI sends a provider with every turn because it needs one for worker
    routing, and the server read the branch pin only when nobody had said anything
    — which is almost never. So a branch pinned to Claude was answered by Codex.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("pinned")
        store.create_branch("loose")
        store.set_branch_llm("pinned", {"provider": "claude", "model": "opus[1m]"})
        return root, store

    def test_the_pin_beats_the_requested_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            self.assertEqual(
                ctxgit.branch_provider_authority(root, "pinned", "codex"), "claude"
            )
            # Worker routing is Codex-only, so it drops out with the provider.
            self.assertEqual(
                ctxgit.branch_provider_authority(root, "pinned", "codex-worker"), "claude"
            )

    def test_an_unpinned_branch_still_honours_the_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            self.assertEqual(
                ctxgit.branch_provider_authority(root, "loose", "codex-worker"), "codex-worker"
            )
            self.assertIsNone(ctxgit.branch_provider_authority(root, "loose", None))

    def test_the_pinned_model_travels_with_the_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            resolved = ctxgit.read_llm_config(root, "pinned")
            self.assertEqual(resolved["provider"], "claude")
            self.assertEqual(resolved["claude"]["model"], "opus[1m]")


class RequestHandlerScopeTest(unittest.TestCase):
    """Handlers that consult a branch pin must actually have a branch.

    `branch_provider_authority` was added to every endpoint that reads a provider
    off the request body, including two that have no branch: the contexts chat is
    project-wide and a merge spans several branches. Both raised NameError, the
    handler thread died mid-response, and the browser reported "Failed to fetch" —
    a network error for what was a missing local variable.
    """

    def test_every_branch_pin_lookup_has_a_branch_in_scope(self) -> None:
        lines = Path(ctxgit.__file__).read_text(encoding="utf-8").split("\n")
        call = "branch_provider_authority(root, branch_id, provider)"
        sites = [index for index, line in enumerate(lines) if call in line]
        self.assertTrue(sites, "the pin lookup vanished; this guard is now pointless")
        for index in sites:
            window = lines[max(0, index - 14) : index]
            self.assertTrue(
                any("branch_id = " in line for line in window),
                f"{call} at line {index + 1} has no branch_id assigned above it",
            )


class AddBranchBesideTest(unittest.TestCase):
    """"Add one here" makes an empty sibling — it copies nothing.

    Branches fork off `initial` into folders like Sales. Starting the next Sales
    branch by forking anything — the branch or its parent — brought a conversation
    and a directory of artifacts, resources and workspace files with it. This
    creates a blank branch instead: parent set to the pointed-at branch's parent so
    it sits beside it, filed in the folder the user was standing in.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("initial", title="Initial")
        store.append_history("initial", "user", "SHARED_BASE")
        store.create_branch("sales_a", title="Sales A", parent="initial")
        store.set_branch_folder("sales_a", "Sales")
        store.append_history("sales_a", "user", "ONLY_A")
        (store.branch_paths("sales_a").root / "artifacts").mkdir(exist_ok=True)
        (store.branch_paths("sales_a").root / "artifacts" / "note.md").write_text("x", encoding="utf-8")
        return root, store

    def _add_beside(self, store, beside: str, target: str) -> str:
        """What the endpoint does, kept in one place so the test pins the behaviour."""
        beside_meta = ctxgit.load_json(store.branch_paths_for_read(beside).meta)
        folder = str(beside_meta.get("folder") or "")
        parent = str(beside_meta.get("parent") or beside_meta.get("forkedFrom") or "").strip()
        store.create_branch(target, title=target, parent=parent or None)
        store.set_branch_folder(target, folder)
        return parent

    def test_the_new_branch_is_empty_and_carries_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            self._add_beside(store, "sales_a", "sales_b")

            self.assertEqual(list(store.iter_history("sales_b")), [])
            artifacts = store.branch_paths("sales_b").root / "artifacts"
            self.assertFalse(
                artifacts.exists() and any(artifacts.iterdir()),
                "a fresh branch must not inherit the sibling's artifacts",
            )

    def test_it_sits_beside_the_branch_rather_than_under_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            parent = self._add_beside(store, "sales_a", "sales_b")

            self.assertEqual(parent, "initial")
            meta = ctxgit.load_json(store.branch_paths("sales_b").meta)
            self.assertEqual(meta.get("parent"), "initial")
            self.assertEqual(meta.get("folder"), "Sales")
            # Nothing about it should look forked.
            self.assertNotIn("forkedFrom", meta)
            self.assertNotIn("forkedAtIndex", meta)

    def test_a_branch_with_no_parent_gives_a_parentless_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            parent = self._add_beside(store, "initial", "fresh")
            self.assertEqual(parent, "")
            self.assertEqual(list(store.iter_history("fresh")), [])

    def test_the_branch_pointed_at_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            self._add_beside(store, "sales_a", "sales_b")
            self.assertEqual(
                [record["text"] for record in store.iter_history("sales_a")], ["ONLY_A"]
            )
            self.assertEqual(
                ctxgit.load_json(store.branch_paths("sales_a").meta).get("folder"), "Sales"
            )


class SequenceSeatProviderTest(unittest.TestCase):
    """Each seat in a room can run on its own provider and model.

    A room used to resolve one provider and run every reply on it, so a writer and
    the evaluator grading it were the same model — one model marking its own work.
    """

    def _room(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("writer")
        store.create_branch("critic")
        store.create_sequence_room(
            ["writer", "critic"], "room", "Room", ["Write.", "Critique."],
            ["info-chat", "info-chat"], 4,
        )
        store.update_sequence_speaking_order("room", [1, 2], evaluator_order=None, update_evaluator=True)
        return root, store

    def _run(self, root, store):
        calls: list[dict] = []
        original = ctxgit.call_provider_prompt

        def fake(provider, _root, _prompt, **kwargs):
            calls.append({"provider": provider, "model": kwargs.get("model_override", "")})
            return {"assistant": f"reply {len(calls)}"}

        ctxgit.call_provider_prompt = fake
        try:
            ctxgit.run_sequence_room_turn(root, store, "room", "go", run_mode="info-chat")
        finally:
            ctxgit.call_provider_prompt = original
        return calls

    def test_seats_run_on_what_they_were_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            store.update_sequence_participant("room", 1, llm={"provider": "claude", "model": "fable"})
            store.update_sequence_participant("room", 2, llm={"provider": "codex", "model": "gpt-5.6-luna"})
            calls = self._run(root, store)
            self.assertEqual(calls[0], {"provider": "claude", "model": "fable"})
            self.assertEqual(calls[1], {"provider": "codex", "model": "gpt-5.6-luna"})

    def test_a_seat_that_says_nothing_follows_the_room(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            store.update_sequence_participant("room", 1, llm={"provider": "claude", "model": "fable"})
            calls = self._run(root, store)
            self.assertEqual(calls[0]["provider"], "claude")
            # Seat 2 was never pinned, so it runs on the room's provider.
            self.assertEqual(calls[1]["provider"], "codex")
            self.assertEqual(calls[1]["model"], "")

    def test_clearing_a_seat_hands_it_back_to_the_room(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            store.update_sequence_participant("room", 1, llm={"provider": "claude", "model": "fable"})
            participant = store.update_sequence_participant("room", 1, llm={"provider": None, "model": None})
            self.assertNotIn("llm", participant)

    def test_a_model_is_checked_against_its_own_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._room(tmp)
            with self.assertRaises(ValueError):
                store.update_sequence_participant("room", 1, llm={"provider": "claude", "model": "gpt-5.6-sol"})


class CodexModelListTest(unittest.TestCase):
    """The Codex list has to name models the installed CLI actually accepts.

    A model offered in the picker but unknown to the CLI is worse than absent: it
    looks selectable and then every turn on it fails.
    """

    def test_astra_is_offered_and_accepted(self) -> None:
        offered = [item["id"] for item in ctxgit.LLM_PROVIDER_MODELS["codex"]]
        self.assertEqual(offered[0], "gpt-6-astra", "the frontier model leads the list")
        self.assertIn("gpt-5.6-sol", offered)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            original = ctxgit.provider_status
            ctxgit.provider_status = lambda _root: {"ok": True, "provider": "codex"}
            try:
                for model in offered:
                    ctxgit.write_provider_config(root, {"provider": "codex", "model": model})
                    self.assertEqual(ctxgit.read_llm_config(root)["codex"]["model"], model)
                with self.assertRaises(ValueError):
                    ctxgit.write_provider_config(root, {"provider": "codex", "model": "gpt-6-nope"})
            finally:
                ctxgit.provider_status = original

    def test_the_claude_tier_map_still_points_at_models_we_offer(self) -> None:
        offered = {item["id"] for item in ctxgit.LLM_PROVIDER_MODELS["codex"]}
        for tier, codex_model in ctxgit.CLAUDE_TO_CODEX_TIER.items():
            self.assertIn(codex_model, offered, f"tier {tier} maps to a model not offered")


class SessionContinuityTest(unittest.TestCase):
    """Branch turns resume the branch's own session, and send only what is new.

    Continuity was removed once already because it was paired with re-sending the
    rebuilt context every turn: the branch history stacked one copy deeper per turn
    and the current guiding block ended up buried among superseded ones. The thing
    that makes it safe is the continuation prompt, so these tests pin both halves.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("b1")
        store.append_history("b1", "user", "EARLIER_TURN")
        store.append_history("b1", "assistant", "EARLIER_ANSWER")
        return root, store

    def test_a_continuation_omits_what_the_session_already_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            full = ctxgit.build_chat_prompt(store, "b1", "next question")
            cont = ctxgit.build_continuation_prompt(store, "b1", "next question")

            self.assertIn("EARLIER_TURN", full)
            self.assertNotIn("EARLIER_TURN", cont, "the session already has this")
            self.assertNotIn("<branch_report>", cont)
            self.assertIn("next question", cont)
            self.assertLess(len(cont), len(full) // 2)

    def test_guiding_is_restated_on_every_continuation(self) -> None:
        # The one thing that must beat everything earlier in the session.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            document = store.create_knowledge_document("House Style")
            store.append_knowledge_entry(document["id"], "## Rule\n\nGUIDING_FACT")
            store.set_branch_guiding("b1", [document["id"]])
            cont = ctxgit.build_continuation_prompt(
                store, "b1", "next", guiding_context=ctxgit.chat_guiding_context(store, "b1")
            )
            self.assertIn("Before answering, check your draft", cont)

    def test_a_session_is_keyed_so_a_changed_setup_starts_a_new_one(self) -> None:
        base = ctxgit.session_key("b1", "chat", "claude", "opus", "guiding text")
        self.assertEqual(base, ctxgit.session_key("b1", "chat", "claude", "opus", "guiding text"))
        # A different model, provider, mode, branch, or guiding is a different session.
        self.assertNotEqual(base, ctxgit.session_key("b1", "chat", "claude", "fable", "guiding text"))
        self.assertNotEqual(base, ctxgit.session_key("b1", "chat", "codex", "opus", "guiding text"))
        self.assertNotEqual(base, ctxgit.session_key("b1", "info-chat", "claude", "opus", "guiding text"))
        self.assertNotEqual(base, ctxgit.session_key("b2", "chat", "claude", "opus", "guiding text"))
        self.assertNotEqual(base, ctxgit.session_key("b1", "chat", "claude", "opus", "REPLACED rules"))

    def test_the_store_survives_having_no_file_yet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            self.assertEqual(ctxgit.remembered_session(root, "anything"), "")
            ctxgit.remember_session(root, "k", "sess-1")
            self.assertEqual(ctxgit.remembered_session(root, "k"), "sess-1")
            ctxgit.forget_session(root, "k")
            self.assertEqual(ctxgit.remembered_session(root, "k"), "")

    def test_continuity_can_be_switched_off(self) -> None:
        self.assertTrue(ctxgit.session_continuity_enabled({}))
        self.assertFalse(ctxgit.session_continuity_enabled({"sessionContinuity": False}))


class CodexOutputDepthTest(unittest.TestCase):
    """Codex answers short because its models ship that way, not because we asked.

    Every Codex model defaults to `verbosity: "low"`, and the frontier ones
    (`gpt-5.6-sol`, `gpt-6-astra`) to `reasoning: "low"` as well — the shortest and
    shallowest combination available. ctxgit set neither, so the same prompt that
    made Claude write a page made Codex answer in three lines.
    """

    def test_depth_is_named_rather_than_left_to_the_model_default(self) -> None:
        cmd: list[str] = []
        ctxgit.apply_codex_output_depth(cmd, {})
        joined = " ".join(cmd)
        self.assertIn('model_verbosity="medium"', joined)
        self.assertIn('model_reasoning_effort="xhigh"', joined)

    def test_a_project_can_set_its_own_depth(self) -> None:
        cmd: list[str] = []
        ctxgit.apply_codex_output_depth(cmd, {"verbosity": "high", "reasoningEffort": "max"})
        joined = " ".join(cmd)
        self.assertIn('model_verbosity="high"', joined)
        self.assertIn('model_reasoning_effort="max"', joined)

    def test_a_level_codex_would_reject_is_dropped(self) -> None:
        # Better to fall through to the model default than to hand Codex a value
        # it refuses and fail the turn.
        cmd: list[str] = []
        ctxgit.apply_codex_output_depth(cmd, {"verbosity": "ultra", "reasoningEffort": "nope"})
        joined = " ".join(cmd)
        self.assertNotIn("model_verbosity", joined, "ultra is a reasoning level, not a verbosity one")
        self.assertNotIn("model_reasoning_effort", joined)

    def test_both_codex_transports_carry_it(self) -> None:
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        # `codex exec` gets it through the session config; the app-server path is a
        # different command builder and had to be wired separately.
        self.assertIn("apply_codex_output_depth(cmd, config)", source)
        self.assertIn('apply_codex_output_depth(cmd, read_llm_config(root).get("codex", {}))', source)


class TurnNarrationTest(unittest.TestCase):
    """What the agent said while working stays on the turn.

    The live panel is cleared when a turn ends, so the only account of how the
    answer was reached used to vanish with it — it survived only in the job's event
    file, which the branch never shows.
    """

    def test_narration_is_kept_and_machinery_is_not(self) -> None:
        collected: list[str] = []
        progress = ctxgit.narration_collecting_progress(None, collected)
        for line in [
            "Preparing branch context",          # ctxgit step label
            "Using tool: Bash · npx tsc",        # machinery
            "Now the regression test that reproduces the failure:",
            "Command finished",                  # machinery
            "프로세스 종료 코드: 0",              # machinery
            "실행 중 발견한 오류도 고쳤습니다.",
            "완료됨",                            # machinery
        ]:
            progress(line)
        self.assertEqual(
            collected,
            ["Now the regression test that reproduces the failure:", "실행 중 발견한 오류도 고쳤습니다."],
        )

    def test_a_repeated_line_is_not_stored_twice(self) -> None:
        collected: list[str] = []
        progress = ctxgit.narration_collecting_progress(None, collected)
        progress("Looking at the parser now")
        progress("Looking at the parser now")
        self.assertEqual(len(collected), 1)

    def test_the_wrapper_passes_cancellation_and_interjections_through(self) -> None:
        # It sits in front of the real callback, so the turn must still be able to
        # be stopped and spoken to.
        def base(_message: str) -> None:
            return None

        base.cancelled = lambda: True
        base.take_interjections = lambda: ["hi"]
        wrapped = ctxgit.narration_collecting_progress(base, [])
        self.assertTrue(getattr(wrapped, "cancelled")())
        self.assertEqual(getattr(wrapped, "take_interjections")(), ["hi"])

    def test_narration_never_reaches_a_later_prompt(self) -> None:
        # Stored beside the record, not inside its text: the prompt builder reads
        # role and text only, so working notes do not become context forever.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            store.create_branch("b1")
            store.append_history(
                "b1", "assistant", "THE_ANSWER", extra={"progress": ["WORKING_NOTE"]}
            )
            prompt = ctxgit.build_chat_prompt(store, "b1", "next")
            self.assertIn("THE_ANSWER", prompt)
            self.assertNotIn("WORKING_NOTE", prompt)
            # But the branch payload carries it, so the chat can show it.
            payload = ctxgit.branch_payload(store, "b1")
            self.assertEqual(payload["history"][-1]["progress"], ["WORKING_NOTE"])


class RuntimeDirectiveTest(unittest.TestCase):
    """A send-mode turn is allowed to finish the job it was opened for.

    The standing contract forbade push, publish and deploy in every mode, so a
    writable turn would build, test and commit and then stop at the last step to
    report it was not permitted to ship. The sandbox and the approval gate are the
    boundaries; that sentence only made the end of the turn useless.
    """

    def test_a_writable_turn_is_not_told_to_stop_short_of_shipping(self) -> None:
        writable = ctxgit.ctxgit_runtime_directive(writable=True)
        self.assertNotIn("Do not push", writable)
        self.assertNotIn("deploy", writable)

    def test_a_read_only_turn_still_is(self) -> None:
        read_only = ctxgit.ctxgit_runtime_directive(writable=False)
        self.assertIn("Do not push, publish, or deploy.", read_only)

    def test_the_outside_workspace_rule_survives_both(self) -> None:
        # That one is a mechanism (approvalRequests), not a request.
        for writable in (True, False):
            directive = ctxgit.ctxgit_runtime_directive(writable=writable)
            self.assertIn("outside the current working directory", directive)
            self.assertIn("Return the required structured output", directive)

    def test_codex_read_only_paths_keep_the_ban(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctxgit.ContextStore(root).init(create_initial_branch=False)
            for writable, expected in ((False, True), (True, False)):
                cmd: list[str] = []
                ctxgit.apply_codex_session_config(cmd, root, writable=writable)
                joined = " ".join(cmd)
                self.assertEqual("Do not push" in joined, expected)

    def test_one_wording_serves_every_provider_and_transport(self) -> None:
        """Three hand-maintained copies became one function.

        Claude, `codex exec` and the Codex app-server each carried their own copy of
        this sentence, so a change to the contract had to be made three times or the
        providers quietly diverged.
        """
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        # The sentence lives only in the helper (twice: writable and read-only).
        self.assertEqual(source.count("You are running inside ctxgit."), 2)
        # One use per surface: codex exec, the codex app-server, and Claude.
        self.assertEqual(source.count("ctxgit_runtime_directive(writable="), 3)


class CodexCommentaryTest(unittest.TestCase):
    """Codex does talk between tool calls; ctxgit was dropping it.

    The app-server sends `agentMessage` items with `phase: "commentary"` around
    each tool call. The progress formatter handled four item types and none of them
    was that, so every Codex turn showed as an unbroken run of "Running command:".
    """

    def _event(self, method: str, item: dict) -> dict:
        return {"method": method, "params": {"item": item}}

    def test_commentary_becomes_progress(self) -> None:
        said = ctxgit.codex_app_server_progress(
            self._event(
                "item/completed",
                {"type": "agentMessage", "phase": "commentary", "text": "I'm about to run the build."},
            )
        )
        self.assertEqual(said, "I'm about to run the build.")

    def test_the_answer_itself_is_not_narrated_twice(self) -> None:
        # The turn's answer comes back as structured output; only commentary is
        # progress, or the whole reply would appear in the log and again as the reply.
        for phase in ("final", "", "answer"):
            self.assertEqual(
                ctxgit.codex_app_server_progress(
                    self._event(
                        "item/completed",
                        {"type": "agentMessage", "phase": phase, "text": "THE WHOLE ANSWER"},
                    )
                ),
                "",
            )

    def test_tool_lines_still_report(self) -> None:
        self.assertEqual(
            ctxgit.codex_app_server_progress(
                self._event("item/started", {"type": "commandExecution", "command": "npm test"})
            ),
            "Running command: npm test",
        )

    def test_commentary_counts_as_narration_and_tool_lines_do_not(self) -> None:
        # So it lands in the turn's stored working log, and the machinery does not.
        self.assertTrue(ctxgit.is_progress_narration("I'm about to run the build."))
        self.assertFalse(ctxgit.is_progress_narration("Running command: npm test"))
        self.assertFalse(ctxgit.is_progress_narration("Command finished"))


class CancelKillsTheWholeTreeTest(unittest.TestCase):
    """Stopping a turn has to stop what the turn started.

    A provider turn is a tree: the agent spawns shells, builds, test runners. Only
    the direct child was killed, so Stop returned at once and looked like it had
    worked while `npm test` and a render job carried on in the background — still
    writing into the workspace after the turn was supposedly over.
    """

    def _cancel_after(self, seconds: float):
        flag = {"stop": False}

        def progress(_message: str) -> None:
            return None

        progress.cancelled = lambda: flag["stop"]
        threading.Timer(seconds, lambda: flag.__setitem__("stop", True)).start()
        return progress

    def test_a_grandchild_does_not_survive_the_cancel(self) -> None:
        marker = f"ctxgit-cancel-probe-{os.getpid()}"
        progress = self._cancel_after(1.0)
        with self.assertRaises(ctxgit.JobCancelledError):
            ctxgit.run_process_with_progress(
                ["/bin/sh", "-c", f"sleep 43 # {marker}"], Path("."), 60, progress
            )
        time.sleep(0.5)
        found = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
        self.assertEqual(found.stdout.strip(), "", "the shell's child outlived the cancel")

    def test_every_kill_path_goes_through_the_tree_aware_one(self) -> None:
        # Two runners (the streaming one and the Codex app-server loop) each cancel
        # and time out; a plain process.kill() in any of them leaks the tree again.
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("terminate_process_tree(process)"), 4)
        self.assertEqual(source.count("start_new_session=os.name != \"nt\""), 2)


class TelegramRemoteTest(unittest.TestCase):
    """Driving a branch from chat.

    The workspace runs with full file access, so the gate that matters is not
    politeness — it is that an unexpected sender can reach a machine. Everything
    here is about who is allowed to speak and what a message is allowed to do.
    """

    def _remote(self, root: Path):
        class Jobs:
            def __init__(self): self.created, self.interjected, self.canceled = [], [], []
            def running_jobs(self, root=None): return list(getattr(self, "running", []))
            def create(self, kind, work, root=None, branch=None, mode=None):
                self.created.append({"kind": kind, "branch": branch, "mode": mode}); return {"id": "j1"}
            def interject(self, job_id, text, root=None):
                self.interjected.append((job_id, text)); return {}
            def cancel(self, job_id, root=None):
                self.canceled.append(job_id); return {}

        class State:
            def root(self_inner): return root

        class Registry:
            def list_projects(self, active_root=None): return [{"path": str(root)}]

        jobs = Jobs()
        remote = ctxgit.TelegramRemote(State(), Registry(), jobs)
        sent: list[str] = []
        remote._say = lambda token, chat, text, reply_to=None: sent.append(text) or 1
        return remote, jobs, sent

    def _project(self, tmp: str, env: str) -> Path:
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("alpha")
        store.create_branch("beta")
        (root / ".ctxgit").mkdir(exist_ok=True)
        (root / ".ctxgit" / ".env").write_text(env, encoding="utf-8")
        return root

    # The ctxgit repo's own .env is a fallback for every project, so a machine that
    # has configured an allowlist would otherwise reject this test's sender. Each
    # project below states its own, which is what a real project should do too.
    def _msg(self, text: str, chat: str = "42", user: int = 7) -> dict:
        return {"message": {"text": text, "chat": {"id": chat}, "from": {"id": user}, "message_id": 100}}

    def test_a_message_from_the_wrong_chat_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            remote, jobs, sent = self._remote(root)
            remote._handle(self._msg("/use alpha", chat="999"), "t")
            self.assertEqual(sent, [], "an unknown chat must not even get an answer")
            self.assertEqual(jobs.created, [])

    def test_a_sender_outside_the_allowlist_is_ignored(self) -> None:
        # A group can gain members; matching the chat alone would hand each of them
        # the same control over this machine.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            remote, jobs, sent = self._remote(root)
            remote._handle(self._msg("/use alpha", user=8), "t")
            self.assertEqual(sent, [])
            remote._handle(self._msg("/use alpha", user=7), "t")
            self.assertTrue(sent)

    def test_plain_text_is_read_only_and_send_is_the_writable_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            remote, jobs, sent = self._remote(root)
            remote._handle(self._msg("/use alpha"), "t")
            remote._handle(self._msg("무슨 상태야?"), "t")
            remote._handle(self._msg("/send 빌드 고쳐줘"), "t")
            self.assertEqual([c["kind"] for c in jobs.created], ["info-chat", "chat"])
            self.assertEqual([c["branch"] for c in jobs.created], ["alpha", "alpha"])

    def test_a_reply_to_a_notification_addresses_that_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            ctxgit.remember_telegram_reply(root, 555, "beta")
            remote, jobs, sent = self._remote(root)
            update = self._msg("이어서 해줘")
            update["message"]["reply_to_message"] = {"message_id": 555}
            remote._handle(update, "t")
            self.assertEqual([c["branch"] for c in jobs.created], ["beta"])

    def test_a_busy_branch_is_interjected_rather_than_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            remote, jobs, sent = self._remote(root)
            jobs.running = [{"id": "live", "branch": "alpha", "mode": "chat"}]
            remote._handle(self._msg("/use alpha"), "t")
            remote._handle(self._msg("그거 말고 이거부터"), "t")
            self.assertEqual(jobs.interjected, [("live", "그거 말고 이거부터")])
            self.assertEqual(jobs.created, [])

    def test_a_branch_name_can_be_shortened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(
                tmp, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=42\nTELEGRAM_ALLOWED_USER_IDS=7\n"
            )
            remote, _, _ = self._remote(root)
            self.assertEqual(remote._resolve_branch(root, "alp"), "alpha")
            self.assertEqual(remote._resolve_branch(root, "nope"), "")


class ForeignJobVisibilityTest(unittest.TestCase):
    """A turn started elsewhere has to look like one started here.

    The Telegram remote can run in its own process, and its jobs live in the same
    files but not in this server's memory. Without reading them the browser shows
    no running marker, no live progress, and the answer only appears on a reload.
    """

    def _store(self, tmp: str):
        root = Path(tmp)
        ctxgit.ContextStore(root).init(create_initial_branch=False)

        class State:
            def root(self_inner): return root

        registry = ctxgit.JobStore(State())
        return root, registry

    def _write_job(self, root: Path, job_id: str, status: str, age_seconds: float = 0.0) -> None:
        jobs_dir = root / "contexts" / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        path = jobs_dir / f"{job_id}.json"
        ctxgit.dump_json(path, {
            "id": job_id, "status": status, "branch": "alpha", "mode": "chat",
            "projectPath": str(root), "events": [],
        })
        if age_seconds:
            old = time.time() - age_seconds
            os.utime(path, (old, old))

    def test_a_live_job_from_another_process_is_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, jobs = self._store(tmp)
            self._write_job(root, "20260919T120000000000Z", "running")
            listed = [j["id"] for j in jobs.running_jobs(root=root)]
            self.assertEqual(listed, ["20260919T120000000000Z"])

    def test_a_job_whose_process_died_drops_out(self) -> None:
        # It stopped being written to, so nothing is keeping it alive.
        with tempfile.TemporaryDirectory() as tmp:
            root, jobs = self._store(tmp)
            self._write_job(root, "20260919T110000000000Z", "running", age_seconds=600)
            self.assertEqual(jobs.running_jobs(root=root), [])

    def test_a_finished_job_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, jobs = self._store(tmp)
            self._write_job(root, "20260919T130000000000Z", "done")
            self.assertEqual(jobs.running_jobs(root=root), [])

    def test_the_browser_adopts_foreign_turns_on_a_timer(self) -> None:
        # Otherwise the page only learns about them when it is reloaded.
        source = Path(__file__).resolve().parents[1].joinpath("web", "app.js").read_text(encoding="utf-8")
        self.assertIn("rehydrateRunningJobs().catch(() => {});\n}, 5000);", source)


class AnswerEnvelopeNotNarrationTest(unittest.TestCase):
    """The reply is not commentary, even though it arrives on the same channel.

    Claude streams its final structured answer as ordinary assistant text, so the
    `{"assistant": ...}` envelope was shown in the progress panel as if the agent
    had said it — a wall of JSON in the place where the answer was about to be
    rendered properly a moment later.
    """

    ENVELOPE = '```json { "assistant": "긴 답변", "artifacts": [], "approvalRequests": [] } ```'

    def test_the_envelope_is_not_treated_as_something_said(self) -> None:
        self.assertTrue(ctxgit.looks_like_chat_envelope(self.ENVELOPE))
        self.assertTrue(ctxgit.looks_like_chat_envelope('{"assistant": "x", "artifacts": []}'))
        self.assertFalse(ctxgit.is_progress_narration(self.ENVELOPE))

    def test_real_commentary_still_counts(self) -> None:
        for line in ("Now running the gate to see whether it measures.", "실행 중 오류도 고쳤습니다."):
            self.assertFalse(ctxgit.looks_like_chat_envelope(line))
            self.assertTrue(ctxgit.is_progress_narration(line))

    def test_the_stream_formatter_drops_it(self) -> None:
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": self.ENVELOPE}]},
        })
        self.assertEqual(ctxgit.claude_stream_progress(event), "")

    def test_the_stream_formatter_keeps_commentary(self) -> None:
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Now checking the build."}]},
        })
        self.assertIn("Now checking the build", ctxgit.claude_stream_progress(event))

    def test_the_browser_hides_it_too(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("web", "app.js").read_text(encoding="utf-8")
        self.assertIn("function looksLikeChatEnvelope", source)
        self.assertIn("if (looksLikeChatEnvelope(text)) return false;", source)


class TrackedSnapshotPruningTest(unittest.TestCase):
    """The output scan must not walk the whole workspace.

    It runs twice a turn — once before the model and once after — so the second
    call lands exactly in the gap before an answer appears. `rglob` descended into
    every directory and discarded the results afterwards, which on a workspace with
    vendored checkouts and browser profiles cost about nine seconds a call.
    """

    def _workspace(self, tmp: str) -> Path:
        root = Path(tmp)
        ctxgit.ContextStore(root).init(create_initial_branch=False)
        (root / "out").mkdir()
        (root / "out" / "deck.pdf").write_bytes(b"%PDF-1.4 real")
        # The kinds of directory that made the walk expensive.
        for noisy in ("node_modules/pkg", ".chrome-profile/Default", ".ctxgit/git/objects"):
            target = root / noisy
            target.mkdir(parents=True, exist_ok=True)
            (target / "buried.pdf").write_bytes(b"%PDF-1.4 noise")
        return root

    def test_only_real_output_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._workspace(tmp)
            found = set(ctxgit.tracked_file_snapshot(root))
            self.assertIn("out/deck.pdf", found)
            self.assertEqual(
                [p for p in found if "node_modules" in p or p.startswith(".")],
                [],
                "vendored and hidden directories must not be scanned",
            )

    def test_the_pruned_directories_are_never_entered(self) -> None:
        # Not just filtered afterwards: entering them is the cost.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._workspace(tmp)
            visited: list[str] = []
            original = os.walk

            def watched(path, *args, **kwargs):
                for current, dirnames, filenames in original(path, *args, **kwargs):
                    visited.append(str(current))
                    yield current, dirnames, filenames

            os.walk = watched
            try:
                ctxgit.tracked_file_snapshot(root)
            finally:
                os.walk = original
            self.assertFalse(
                [v for v in visited if "node_modules" in v or "/.ctxgit/git" in v],
                "the walk descended into a directory it was going to discard",
            )


class TelegramSequenceRoomRoutingTest(unittest.TestCase):
    """A room driven from chat has to run as a room.

    A sequence room is an ordered set of agents with its own turn function, not a
    chat branch. Sending it an ordinary chat turn produced nothing visible, so a
    question asked from the phone looked simply unanswered.
    """

    def test_a_room_branch_runs_the_room_turn(self) -> None:
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        start = source.index("def _start_turn(")
        body = source[start : start + 2000]
        self.assertIn("branch_is_sequence_room(store, branch)", body)
        self.assertIn("run_sequence_room_turn(", body)
        # And the room's own mode decides read-only vs writable.
        self.assertIn('run_mode="send" if writable else "info-chat"', body)

    def test_a_failing_poller_says_so(self) -> None:
        # Telegram allows one getUpdates at a time; a second caller gets 409. When
        # that was silent, a stalled poller looked exactly like a dead thread.
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        self.assertIn("telegram remote: retrying after", source)


class _BossJobs:
    """A JobStore stand-in: records what would have been started, runs nothing."""

    def __init__(self):
        self.created, self.interjected, self.running = [], [], []

    def running_jobs(self, root=None):
        return list(self.running)

    def create(self, kind, work, root=None, branch=None, mode=None):
        self.created.append({"kind": kind, "branch": branch, "mode": mode, "work": work})
        return {"id": f"job-{len(self.created)}"}

    def interject(self, job_id, text, root=None):
        self.interjected.append((job_id, text))
        return {}


class _BossModel:
    """Swap the provider call for a canned answer, capturing the prompt."""

    def __init__(self, answer, raw=False):
        self.answer, self.prompts, self.raw = answer, [], raw

    def __enter__(self):
        self.original = ctxgit.call_provider_prompt

        def fake(provider, root, prompt, **kwargs):
            self.prompts.append(prompt)
            if self.raw:
                return self.answer
            answer = self.answer
            if isinstance(answer, dict) and "assignments" in answer and "<feedback>" not in prompt:
                rows = [a for a in answer["assignments"] if isinstance(a, dict)]
                if "<brief>" in prompt:
                    # Step two: the writer for one branch. Tests state what each
                    # branch ends up being told; hand this branch its line.
                    branch = prompt.split("Branch:\n### ", 1)[1].split("\n", 1)[0]
                    row = next((a for a in rows if a.get("branch") == branch), {})
                    answer = {
                        "instruction": row.get("instruction", ""),
                        "suggestedMode": row.get("suggestedMode", "info-chat"),
                    }
                else:
                    # Step one: the split. Every named branch gets a brief.
                    answer = {
                        "summary": answer.get("summary", ""),
                        "assignments": [{"branch": a.get("branch"), "brief": a.get("instruction")} for a in rows],
                    }
            # The shape providers really return: a chat envelope, with the object
            # that was asked for as fenced text in `assistant`. A fake that handed
            # the dict straight back is how a desk that could never draft passed.
            text = json.dumps(answer, ensure_ascii=False, indent=2)
            return {"assistant": f"```json\n{text}\n```", "artifacts": [], "approvalRequests": []}

        ctxgit.call_provider_prompt = fake
        return self

    def __exit__(self, *exc):
        ctxgit.call_provider_prompt = self.original


class BossChatTest(unittest.TestCase):
    """Boss chat drafts, the user reviews, then it dispatches.

    Nothing is sent on the model's say-so: the wording each branch receives is
    shown first and can be edited, argued with, or dropped. That review step is the
    feature — it is the difference between delegating and being surprised.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("sales", title="Sales")
        store.set_branch_folder("sales", "Sales")
        store.create_branch("dev", title="Dev")
        store.set_branch_folder("dev", "Dev")
        store.create_branch("untouched", title="Untouched")
        return root, store

    def _draft(self, root, store, assignments, message="오늘 할 일", summary="나눴습니다"):
        with _BossModel({"assignments": assignments, "summary": summary}):
            return ctxgit.draft_boss_assignments(root, store, message)

    def test_drafting_sends_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            items = self._draft(root, store, [
                {"branch": "sales", "instruction": "견적 정리", "suggestedMode": "send"},
            ])
            self.assertEqual([i["branch"] for i in items], ["sales"])
            self.assertEqual(items[0]["request"], "오늘 할 일")
            # The model may hint at a mode; it never gets to choose one.
            self.assertEqual(items[0]["suggestedMode"], "send")
            self.assertNotIn("mode", items[0])
            history = ctxgit.iter_boss_history(store)
            self.assertEqual([r["role"] for r in history], ["user", "assistant"])
            self.assertEqual(history[0]["text"], "오늘 할 일")
            self.assertEqual(history[1]["kind"], "draft")
            for branch in ("sales", "dev"):
                self.assertEqual(list(store.iter_history(branch)), [], "no branch was spoken to")

    # 🚨 The desk writes *to* branches. A draft composed from a two-line summary is
    #    guesswork wearing the user's voice — it cannot pick up what the branch
    #    already decided or the terms that conversation uses. Tone is a product of
    #    that context, not of an instruction about tone.
    def test_a_branch_is_offered_at_a_turns_depth_not_a_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            store.append_history("sales", "user", "단가는 월 단위로 끊어서 적어줘")
            store.append_history("sales", "assistant", "월 단위로 고쳤습니다. 분기는 빼 두었습니다.")
            model = _BossModel({"assignments": [], "summary": ""})
            with model:
                ctxgit.draft_boss_assignments(root, store, "견적 다시 봐줘")
            prompt = model.prompts[0]
            self.assertIn("recent history:", prompt)
            self.assertIn("단가는 월 단위로 끊어서 적어줘", prompt)
            self.assertIn("월 단위로 고쳤습니다", prompt)

    # One branch gets what a turn with it would get; a wide desk thins evenly and
    # never drops below the floor. Both ends matter: the old code gave every branch
    # a flat 2000 characters no matter how few or how many there were.
    def test_the_context_budget_is_split_across_the_chosen_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            full = ctxgit.boss_branch_context_budget(store, 1)
            self.assertEqual(full, ctxgit.DEFAULT_CONTEXT_BUDGET_CHARS)
            self.assertEqual(ctxgit.boss_branch_context_budget(store, 4), full // 4)
            self.assertEqual(
                ctxgit.boss_branch_context_budget(store, 1000),
                ctxgit.BOSS_MIN_BRANCH_CONTEXT_CHARS,
            )

    # 🚨 Splitting and writing are separate calls. One call for everything meant every
    #    chosen branch shared a single prompt's budget — the wider the desk, the less
    #    each draft knew about the branch it was written for.
    def test_each_branch_gets_its_own_writer_at_full_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev", "untouched"])
            store.append_history("sales", "assistant", "세일즈만 아는 이야기")
            store.append_history("dev", "assistant", "개발만 아는 이야기")
            seen_budgets = []
            original = ctxgit.boss_branch_context_block

            def spy(st, branch_id, budget):
                seen_budgets.append(budget)
                return original(st, branch_id, budget)

            ctxgit.boss_branch_context_block = spy
            try:
                with _BossModel({"assignments": [
                    {"branch": "sales", "instruction": "견적"},
                    {"branch": "dev", "instruction": "빌드"},
                ], "summary": "나눴습니다"}) as model:
                    items = ctxgit.draft_boss_assignments(root, store, "오늘 할 일")
            finally:
                ctxgit.boss_branch_context_block = original
            self.assertEqual(sorted(i["branch"] for i in items), ["dev", "sales"])
            split = [p for p in model.prompts if "<brief>" not in p]
            writers = [p for p in model.prompts if "<brief>" in p]
            self.assertEqual(len(split), 1)
            self.assertEqual(len(writers), 2, "one writer per branch that has work, none for the idle one")
            # The split stays light: no branch history in it.
            self.assertNotIn("세일즈만 아는 이야기", split[0])
            # A writer sees its own branch in depth, and only its own.
            sales = next(p for p in writers if "### sales" in p)
            self.assertIn("세일즈만 아는 이야기", sales)
            self.assertNotIn("개발만 아는 이야기", sales)
            # Full budget each — not a third of it.
            self.assertEqual(seen_budgets, [ctxgit.boss_branch_context_budget(store, 1)] * 2)

    def test_one_writer_failing_does_not_lose_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            original = ctxgit.call_provider_prompt

            def fake(provider, r, prompt, **k):
                if "<brief>" not in prompt:
                    return {"assignments": [{"branch": "sales", "brief": "견적"}, {"branch": "dev", "brief": "빌드"}], "summary": ""}
                if "### dev" in prompt:
                    raise RuntimeError("provider down")
                return {"instruction": "견적 정리해줘", "suggestedMode": "send"}

            ctxgit.call_provider_prompt = fake
            try:
                items = ctxgit.draft_boss_assignments(root, store, "오늘 할 일")
            finally:
                ctxgit.call_provider_prompt = original
            self.assertEqual([i["branch"] for i in items], ["sales"])
            self.assertIn("dev", ctxgit.iter_boss_history(store)[-1]["text"])
            self.assertIn("실패", ctxgit.iter_boss_history(store)[-1]["text"])

    def test_a_writer_can_decline_a_brief_that_is_not_its_branch_s_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            with _BossModel({"assignments": [
                {"branch": "sales", "instruction": "견적"},
                {"branch": "dev", "instruction": ""},
            ], "summary": ""}):
                items = ctxgit.draft_boss_assignments(root, store, "오늘 할 일")
            self.assertEqual([i["branch"] for i in items], ["sales"])

    def test_feedback_on_several_drafts_rewrites_each_on_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [
                {"branch": "sales", "instruction": "세일즈 원문"},
                {"branch": "dev", "instruction": "개발 원문"},
            ])
            answer = {"assignments": [
                {"branch": "sales", "instruction": "세일즈 고침"},
                {"branch": "dev", "instruction": "개발 고침"},
            ], "summary": "줄였습니다"}
            with _BossModel(answer) as model:
                ctxgit.revise_boss_items(root, store, "전부 더 짧게")
            self.assertEqual(len(model.prompts), 2)
            for prompt in model.prompts:
                self.assertEqual(("세일즈 원문" in prompt) + ("개발 원문" in prompt), 1, "one draft per rewrite")
            items = {i["branch"]: i["instruction"] for i in ctxgit.boss_pending_items(store)}
            self.assertEqual(items, {"sales": "세일즈 고침", "dev": "개발 고침"})

    def test_the_http_path_can_record_the_request_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            ctxgit.append_boss_history(store, "user", "오늘 할 일")
            with _BossModel({"assignments": [], "summary": ""}):
                ctxgit.draft_boss_assignments(root, store, "오늘 할 일", record_request=False)
            users = [r for r in ctxgit.iter_boss_history(store) if r["role"] == "user"]
            self.assertEqual(len(users), 1, "the request is not recorded twice")

    def test_a_request_nobody_can_take_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self.assertEqual(self._draft(root, store, [], summary=""), [])
            self.assertIn("찾지 못했습니다", ctxgit.iter_boss_history(store)[-1]["text"])

    def test_an_unreadable_reply_fails_loudly(self) -> None:
        # "Succeeded with zero drafts" is what this used to look like.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            envelope = {"assistant": "죄송합니다, 나눌 수 없었습니다.", "artifacts": [], "approvalRequests": []}
            with _BossModel(envelope, raw=True):
                with self.assertRaises(RuntimeError):
                    ctxgit.draft_boss_assignments(root, store, "오늘 할 일")

    def test_prose_around_the_json_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            reply = '써봤습니다.\n{"instruction": "견적", "suggestedMode": "send"}\n이상입니다.'
            with _BossModel({"assistant": reply, "artifacts": [], "approvalRequests": []}, raw=True):
                items = ctxgit.draft_boss_assignments(root, store, "오늘 할 일")
            self.assertEqual([i["branch"] for i in items], ["sales"])

    def test_drafting_needs_a_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            with self.assertRaises(ValueError):
                self._draft(root, store, [])

    def test_only_chosen_branches_survive_the_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            items = self._draft(root, store, [
                {"branch": "sales", "instruction": "견적"},
                {"branch": "untouched", "instruction": "몰래"},
            ])
            self.assertEqual([i["branch"] for i in items], ["sales"])

    def test_the_user_chooses_the_mode_per_branch_per_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [
                {"branch": "sales", "instruction": "견적"},
                {"branch": "dev", "instruction": "빌드"},
            ])
            jobs = _BossJobs()
            payload = ctxgit.dispatch_boss_items(root, store, jobs, [
                {"branch": "sales", "instruction": "견적 정리해줘", "mode": "send"},
                {"branch": "dev", "instruction": "빌드 봐줘", "mode": "info-chat"},
            ])
            self.assertEqual(
                [(c["branch"], c["kind"]) for c in jobs.created],
                [("sales", "chat"), ("dev", "info-chat")],
            )
            self.assertEqual([s["jobId"] for s in payload["started"]], ["job-1", "job-2"])

    def test_dispatch_without_a_mode_is_refused(self) -> None:
        # Send or info-chat is the user's call; there is no default to fall back on.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self._draft(root, store, [{"branch": "sales", "instruction": "견적", "suggestedMode": "send"}])
            jobs = _BossJobs()
            with self.assertRaises(ValueError):
                ctxgit.dispatch_boss_items(root, store, jobs, [{"branch": "sales", "instruction": "견적"}])
            self.assertEqual(jobs.created, [])
            self.assertEqual(len(ctxgit.boss_pending_items(store)), 1, "the draft is still there")

    def test_dispatch_cannot_reach_outside_the_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            jobs = _BossJobs()
            with self.assertRaises(ValueError):
                ctxgit.dispatch_boss_items(root, store, jobs, [
                    {"branch": "untouched", "instruction": "몰래", "mode": "send"},
                ])
            self.assertEqual(jobs.created, [])

    def test_edited_wording_is_what_gets_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self._draft(root, store, [{"branch": "sales", "instruction": "모델이 쓴 문장"}])
            captured = {}
            original = ctxgit.start_branch_turn
            ctxgit.start_branch_turn = lambda r, st, j, b, text, **k: captured.update(text=text, **k) or {"id": "x"}
            try:
                ctxgit.dispatch_boss_items(root, store, _BossJobs(), [
                    {"branch": "sales", "instruction": "내가 고친 문장", "mode": "info-chat"},
                ])
            finally:
                ctxgit.start_branch_turn = original
            self.assertEqual(captured["text"], "내가 고친 문장")
            self.assertFalse(captured["writable"])

    def test_hand_edits_are_kept_on_the_desk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            before = self._draft(root, store, [{"branch": "sales", "instruction": "모델이 쓴 문장"}])[0]
            ctxgit.save_boss_edits(store, [{"branch": "sales", "instruction": "내가 고친 문장"}])
            item = ctxgit.boss_pending_items(store)[0]
            self.assertEqual(item["instruction"], "내가 고친 문장")
            self.assertTrue(item["edited"])
            self.assertEqual(item["id"], before["id"], "an edit is the same draft, not a new one")

    def test_feedback_rewrites_from_the_current_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            before = self._draft(root, store, [
                {"branch": "sales", "instruction": "원래 문장"},
                {"branch": "dev", "instruction": "개발 문장"},
            ])
            ctxgit.save_boss_edits(store, [{"branch": "sales", "instruction": "내가 고친 문장"}])
            answer = {"assignments": [{"branch": "sales", "instruction": "고친 문장", "suggestedMode": "send"}], "summary": "줄였습니다"}
            with _BossModel(answer) as model:
                ctxgit.revise_boss_items(root, store, "더 짧게", only=["sales"])
            self.assertIn("내가 고친 문장", model.prompts[0])
            self.assertIn("더 짧게", model.prompts[0])
            self.assertNotIn("개발 문장", model.prompts[0], "only the named branch is up for rewriting")
            items = {i["branch"]: i for i in ctxgit.boss_pending_items(store)}
            self.assertEqual(items["sales"]["instruction"], "고친 문장")
            self.assertEqual(items["sales"]["revision"], 1)
            self.assertEqual(items["sales"]["request"], "오늘 할 일")
            self.assertNotEqual(items["sales"]["id"], before[0]["id"])
            self.assertEqual(items["dev"]["instruction"], "개발 문장")
            kinds = [r.get("kind") for r in ctxgit.iter_boss_history(store)]
            self.assertEqual(kinds[-2:], ["feedback", "revision"])

    # 🚨 피드백은 초안 **위에서** 나온다. 다시 쓰는 쪽이 브랜치를 모르면, 사용자는
    #    맥락을 아는 글을 보고 말했는데 고치는 쪽은 맥락 없이 고친다 — 매번 같은 자리로
    #    되돌아오는 이유가 그것이다. 라우팅과 같은 깊이여야 한다.
    def test_a_rewrite_sees_the_branch_as_deeply_as_the_first_draft_did(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            store.append_history("sales", "user", "단가는 월 단위로 끊어서 적어줘")
            store.append_history("sales", "assistant", "월 단위로 고쳤습니다.")
            self._draft(root, store, [{"branch": "sales", "instruction": "원래 문장"}])
            answer = {"assignments": [{"branch": "sales", "instruction": "고친 문장"}], "summary": ""}
            with _BossModel(answer) as model:
                ctxgit.revise_boss_items(root, store, "더 짧게", only=["sales"])
            prompt = model.prompts[0]
            self.assertIn("recent history:", prompt)
            self.assertIn("단가는 월 단위로 끊어서 적어줘", prompt)
            self.assertIn("월 단위로 고쳤습니다", prompt)

    # 🚨 두 번째 피드백은 첫 번째가 만들어 낸 문장 위에서 나온다. 앞 라운드가 안 실리면
    #    이미 고친 것을 되돌려 놓고, 사용자는 같은 지적을 두 번 하게 된다.
    def test_a_rewrite_carries_what_it_was_already_told(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self._draft(root, store, [{"branch": "sales", "instruction": "원래 문장"}])
            with _BossModel({"assignments": [{"branch": "sales", "instruction": "존대로 고친 문장"}], "summary": ""}):
                ctxgit.revise_boss_items(root, store, "존대로 써줘", only=["sales"])
            model = _BossModel({"assignments": [{"branch": "sales", "instruction": "마감일까지 넣은 문장"}], "summary": ""})
            with model:
                ctxgit.revise_boss_items(root, store, "마감일도 넣어줘", only=["sales"])
            prompt = model.prompts[0]
            self.assertIn("존대로 써줘", prompt, "앞 라운드 피드백이 따라와야 한다")
            self.assertIn("존대로 고친 문장", prompt, "고치는 대상은 지금 문장이다")
            # 지금 처리할 피드백은 Feedback 절에 한 번만 온다.
            self.assertNotIn("<earlier_feedback>마감일도 넣어줘</earlier_feedback>", prompt)

    def test_a_rewrite_cannot_add_a_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [{"branch": "sales", "instruction": "원래"}])
            answer = {"assignments": [
                {"branch": "sales", "instruction": "고침"},
                {"branch": "dev", "instruction": "끼워넣기"},
            ], "summary": ""}
            with _BossModel(answer):
                ctxgit.revise_boss_items(root, store, "더 짧게")
            self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store)], ["sales"])

    def test_feedback_with_nothing_to_revise_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            with self.assertRaises(ValueError):
                ctxgit.revise_boss_items(root, store, "더 짧게")

    def test_a_busy_branch_is_interjected_instead_of_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self._draft(root, store, [{"branch": "sales", "instruction": "이거 먼저"}])
            jobs = _BossJobs()
            jobs.running = [{"id": "live", "branch": "sales"}]
            ctxgit.dispatch_boss_items(root, store, jobs, [
                {"branch": "sales", "instruction": "이거 먼저", "mode": "info-chat"},
            ])
            self.assertEqual(jobs.interjected, [("live", "이거 먼저")])
            self.assertEqual(jobs.created, [])

    def test_dispatch_records_the_turn_and_clears_only_what_it_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [
                {"branch": "sales", "instruction": "세일즈"},
                {"branch": "dev", "instruction": "빌드 고쳐"},
            ])
            ctxgit.dispatch_boss_items(root, store, _BossJobs(), [
                {"branch": "dev", "instruction": "빌드 고쳐", "mode": "info-chat"},
            ])
            last = ctxgit.iter_boss_history(store)[-1]
            self.assertEqual(last["kind"], "dispatch")
            self.assertIn("dev", last["text"])
            self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store)], ["sales"])
            thread = ctxgit.boss_threads(store)["dev"]
            self.assertEqual(thread["lastInstruction"], "빌드 고쳐")
            self.assertEqual(thread["request"], "오늘 할 일")
            self.assertEqual(thread["lastMode"], "info-chat")

    def test_discarding_one_draft_leaves_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [
                {"branch": "sales", "instruction": "세일즈"},
                {"branch": "dev", "instruction": "개발"},
            ])
            ctxgit.drop_boss_items(store, {"sales"})
            self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store)], ["dev"])
            ctxgit.drop_boss_items(store)
            self.assertEqual(ctxgit.boss_pending_items(store), [])

    def test_deselecting_a_branch_takes_its_draft_off_the_desk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            self._draft(root, store, [
                {"branch": "sales", "instruction": "세일즈"},
                {"branch": "dev", "instruction": "개발"},
            ])
            ctxgit.write_boss_config(store, ["dev"])
            self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store)], ["dev"])

    def test_a_stale_selection_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales", "dev"])
            ctxgit.dump_json(
                ctxgit.boss_config_path(store), {"branches": ["sales", "deleted"]}
            )
            self.assertEqual(ctxgit.read_boss_config(store)["branches"], ["sales"])

    def test_an_unknown_branch_cannot_be_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            with self.assertRaises(ValueError):
                ctxgit.write_boss_config(store, ["nope"])

    def test_reset_clears_the_conversation_and_any_pending_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            self._draft(root, store, [{"branch": "sales", "instruction": "x"}])
            store.reset_boss_chat()
            self.assertEqual(ctxgit.iter_boss_history(store), [])
            self.assertEqual(ctxgit.read_boss_draft(store), {})
            self.assertEqual(ctxgit.read_boss_config(store)["branches"], ["sales"], "the selection survives")

    def test_the_payload_carries_the_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.write_boss_config(store, ["sales"])
            store.append_history("sales", "assistant", "견적 초안 만들었습니다.")
            self._draft(root, store, [{"branch": "sales", "instruction": "견적"}])
            jobs = _BossJobs()
            work_id = ctxgit.add_boss_inflight(store, "", "turn", branch="sales")
            ctxgit.update_boss_inflight(store, work_id, job_id="f", kind="followup")
            jobs.running = [{"id": "f", "branch": ctxgit.boss_followup_job_key("sales")}]
            payload = ctxgit.boss_chat_payload(store, jobs)
            self.assertIn("Sales", payload["folders"])
            rows = {b["id"]: b for b in payload["branches"]}
            self.assertEqual(rows["sales"]["folder"], "Sales")
            self.assertEqual(rows["untouched"]["folder"], "")
            self.assertTrue(rows["sales"]["selected"])
            self.assertIn("견적 초안", rows["sales"]["lastAnswer"])
            self.assertTrue(rows["sales"]["draftingFollowup"])
            self.assertFalse(rows["sales"]["running"], "a follow-up being drafted is not the branch running")
            self.assertNotIn("lastAnswer", rows["untouched"])
            self.assertEqual([i["branch"] for i in payload["pending"]], ["sales"])

    def test_concurrent_writers_do_not_drop_each_other_s_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            for index in range(8):
                store.create_branch(f"b{index}")
            threads = [
                threading.Thread(
                    target=ctxgit.upsert_boss_items,
                    args=(store, [ctxgit.new_boss_item(f"b{index}", "x")]),
                )
                for index in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len(ctxgit.boss_pending_items(store)), 8)


class BossDeskForkTest(unittest.TestCase):
    """"New branch from boss" makes another Boss, not a branch.

    The new desk has the same board — branches, log, drafts, threads — and work that
    was under way when it was split off keeps going on it: a draft still being
    written, or a branch still running, reports to every desk holding its entry.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("sales", title="Sales")
        store.create_branch("dev", title="Dev")
        ctxgit.write_boss_config(store, ["sales", "dev"])
        return root, store

    def test_a_fork_is_a_desk_with_the_same_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            with _BossModel({"assignments": [{"branch": "sales", "instruction": "견적"}], "summary": "s"}):
                ctxgit.draft_boss_assignments(root, store, "오늘 할 일")
            desk = ctxgit.fork_boss_desk(store, "", "견적 스프린트")
            self.assertEqual(ctxgit.boss_desk_ids(store), ["", desk])
            self.assertEqual(ctxgit.read_boss_config(store, desk)["branches"], ["sales", "dev"])
            self.assertEqual(
                [r["text"] for r in ctxgit.iter_boss_history(store, desk)],
                [r["text"] for r in ctxgit.iter_boss_history(store)],
            )
            self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store, desk)], ["sales"])
            desks = {d["id"]: d for d in ctxgit.list_boss_desks(store)}
            self.assertEqual(desks[desk]["title"], "견적 스프린트")
            self.assertTrue(desks[desk]["forked"])
            self.assertFalse(desks[""]["forked"], "only a split-off Boss carries the star")
            # Not a branch: nothing new in the branch list.
            self.assertEqual(sorted(b["id"] for b in store.list_branches()), ["dev", "sales"])

    def test_desks_are_independent_after_the_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            desk = ctxgit.fork_boss_desk(store, "", "Second")
            ctxgit.write_boss_config(store, ["dev"], desk)
            ctxgit.append_boss_history(store, "user", "두 번째 데스크에만", desk=desk)
            self.assertEqual(ctxgit.read_boss_config(store)["branches"], ["sales", "dev"])
            self.assertEqual(ctxgit.iter_boss_history(store), [])
            store.reset_boss_chat(desk)
            self.assertEqual(ctxgit.iter_boss_history(store, desk), [])
            self.assertEqual(ctxgit.read_boss_config(store, desk)["branches"], ["dev"])

    def test_a_draft_in_progress_lands_on_the_fork_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.append_boss_history(store, "user", "오늘 할 일")
            work_id = ctxgit.add_boss_inflight(store, "", "draft")
            ctxgit.update_boss_inflight(store, work_id, job_id="job-1")
            # Split off while the model is still writing.
            desk = ctxgit.fork_boss_desk(store, "", "Mid-draft")
            jobs = _BossJobs()
            jobs.running = [{"id": "job-1", "branch": ctxgit.BOSS_CHAT_KEY}]
            self.assertEqual(
                [d["jobId"] for d in ctxgit.boss_chat_payload(store, jobs, desk)["drafting"]], ["job-1"],
                "the new Boss shows the draft as still being written",
            )
            with _BossModel({"assignments": [{"branch": "sales", "instruction": "견적"}], "summary": "s"}):
                ctxgit.draft_boss_assignments(root, store, "오늘 할 일", work_id=work_id, record_request=False)
            for holder in ("", desk):
                self.assertEqual([i["branch"] for i in ctxgit.boss_pending_items(store, holder)], ["sales"])
                self.assertEqual(ctxgit.iter_boss_history(store, holder)[-1]["kind"], "draft")
                self.assertEqual(ctxgit.read_boss_draft(store, holder).get("inflight"), [])

    def test_a_running_branch_reports_its_follow_up_to_the_fork_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            jobs = _BossJobs()
            original = ctxgit.run_history_chat_turn
            ctxgit.run_history_chat_turn = lambda *a, **k: {"ok": True}
            try:
                ctxgit.dispatch_boss_items(root, store, jobs, [
                    {"branch": "sales", "instruction": "견적 만들어줘", "mode": "info-chat"},
                ])
                desk = ctxgit.fork_boss_desk(store, "", "Mid-turn")  # the branch is still running
                jobs.running = [{"id": "job-1", "branch": "sales"}]
                row = next(b for b in ctxgit.boss_chat_payload(store, jobs, desk)["branches"] if b["id"] == "sales")
                self.assertTrue(row["running"])
                self.assertEqual(row["thread"]["lastInstruction"], "견적 만들어줘")
                store.append_history("sales", "assistant", "초안 만들었습니다.")
                jobs.created[0]["work"](lambda message: None)  # the turn finishes
            finally:
                ctxgit.run_history_chat_turn = original
            self.assertEqual(jobs.created[1]["kind"], "boss-followup")
            answer = {"instruction": "단가도 채워줘", "reason": "단가가 비었습니다", "done": False, "suggestedMode": "send"}
            with _BossModel(answer):
                jobs.created[1]["work"](lambda message: None)
            for holder in ("", desk):
                items = ctxgit.boss_pending_items(store, holder)
                self.assertEqual([(i["branch"], i["origin"]) for i in items], [("sales", "followup")])

    def test_a_failed_turn_clears_its_entry_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            jobs = _BossJobs()
            original = ctxgit.run_history_chat_turn

            def boom(*a, **k):
                raise RuntimeError("provider down")

            ctxgit.run_history_chat_turn = boom
            try:
                ctxgit.dispatch_boss_items(root, store, jobs, [
                    {"branch": "sales", "instruction": "질문", "mode": "info-chat"},
                ])
                desk = ctxgit.fork_boss_desk(store, "", "Fork")
                with self.assertRaises(RuntimeError):
                    jobs.created[0]["work"](lambda message: None)
            finally:
                ctxgit.run_history_chat_turn = original
            for holder in ("", desk):
                self.assertEqual(ctxgit.read_boss_draft(store, holder).get("inflight"), [])

    def test_an_entry_whose_job_died_stops_showing_as_working(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            work_id = ctxgit.add_boss_inflight(store, "", "draft", startedAt="2020-01-01T00:00:00Z")
            ctxgit.update_boss_inflight(store, work_id, job_id="gone")
            self.assertEqual(ctxgit.boss_chat_payload(store, _BossJobs())["drafting"], [])
            self.assertEqual(ctxgit.read_boss_draft(store).get("inflight"), [])

    def test_a_desk_id_never_comes_from_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            for bad in ("../../etc", "nope"):
                with self.assertRaises(ValueError):
                    ctxgit.resolve_boss_desk(store, bad)
            with self.assertRaises(ValueError):
                ctxgit.delete_boss_desk(store, "")
            desk = ctxgit.fork_boss_desk(store, "", "임시")
            ctxgit.delete_boss_desk(store, desk)
            self.assertEqual(ctxgit.boss_desk_ids(store), [""])


class BossFollowUpTest(unittest.TestCase):
    """When a branch answers, the next message is already waiting.

    A delegated task rarely finishes in one exchange, and the moment the answer
    lands is when the next instruction is obvious. Drafting it then keeps the desk
    a step ahead — still as a draft, reviewed like everything else.
    """

    def _project(self, tmp: str):
        root = Path(tmp)
        store = ctxgit.ContextStore(root)
        store.init(create_initial_branch=False)
        store.create_branch("sales", title="Sales")
        ctxgit.write_boss_config(store, ["sales"])
        return root, store

    def _answer(self, instruction, reason="이유", done=False, mode="info-chat"):
        return {"instruction": instruction, "reason": reason, "done": done, "suggestedMode": mode}

    def test_the_answer_becomes_a_reviewable_next_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            with _BossModel({"assignments": [{"branch": "sales", "instruction": "견적 만들어줘"}], "summary": ""}):
                ctxgit.draft_boss_assignments(root, store, "이번 주 견적 마무리")
            ctxgit.dispatch_boss_items(root, store, _BossJobs(), [
                {"branch": "sales", "instruction": "견적 만들어줘", "mode": "send"},
            ])
            store.append_history("sales", "assistant", "견적 초안 만들었고 단가는 확인 못 했습니다.")
            with _BossModel(self._answer("단가는 어디서 막혔는지 알려줘", "단가 확인이 빠졌습니다")) as model:
                ctxgit.draft_boss_followup(root, store, "sales")
            # Written against what was asked and what was last said, not in a vacuum.
            self.assertIn("이번 주 견적 마무리", model.prompts[0])
            self.assertIn("견적 만들어줘", model.prompts[0])
            self.assertIn("단가는 확인 못", model.prompts[0])
            items = ctxgit.boss_pending_items(store)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["origin"], "followup")
            self.assertEqual(items[0]["instruction"], "단가는 어디서 막혔는지 알려줘")
            self.assertIn("단가", items[0]["reason"])
            self.assertEqual(items[0]["request"], "이번 주 견적 마무리")
            # Nothing is sent: it waits for approval like any other draft.
            self.assertEqual(len(list(store.iter_history("sales"))), 1)

    def test_a_finished_turn_schedules_the_next_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            jobs = _BossJobs()
            original = ctxgit.run_history_chat_turn
            ctxgit.run_history_chat_turn = lambda *a, **k: {"ok": True}
            try:
                ctxgit.dispatch_boss_items(root, store, jobs, [
                    {"branch": "sales", "instruction": "질문", "mode": "info-chat"},
                ])
                jobs.created[0]["work"](lambda message: None)  # the branch turn finishes
            finally:
                ctxgit.run_history_chat_turn = original
            self.assertEqual(
                [(c["kind"], c["branch"]) for c in jobs.created],
                [("info-chat", "sales"), ("boss-followup", ctxgit.boss_followup_job_key("sales"))],
            )

    def test_a_failed_turn_schedules_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            jobs = _BossJobs()
            original = ctxgit.run_history_chat_turn

            def boom(*a, **k):
                raise RuntimeError("provider down")

            ctxgit.run_history_chat_turn = boom
            try:
                ctxgit.dispatch_boss_items(root, store, jobs, [
                    {"branch": "sales", "instruction": "질문", "mode": "info-chat"},
                ])
                with self.assertRaises(RuntimeError):
                    jobs.created[0]["work"](lambda message: None)
            finally:
                ctxgit.run_history_chat_turn = original
            self.assertEqual(len(jobs.created), 1)

    def test_a_branch_outside_the_selection_gets_no_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            store.create_branch("stranger")
            store.append_history("stranger", "assistant", "답")
            self.assertEqual(ctxgit.draft_boss_followup(root, store, "stranger"), {})
            self.assertEqual(ctxgit.boss_pending_items(store), [])

    def test_a_branch_that_never_answered_gets_no_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            self.assertEqual(ctxgit.draft_boss_followup(root, store, "sales"), {})

    def test_a_follow_up_replaces_that_branch_s_pending_item(self) -> None:
        # One line per branch on the board; a second answer supersedes the first.
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            store.append_history("sales", "assistant", "1차 답변")
            with _BossModel(self._answer("첫 후속")):
                ctxgit.draft_boss_followup(root, store, "sales")
            ctxgit.dispatch_boss_items(root, store, _BossJobs(), [
                {"branch": "sales", "instruction": "첫 후속", "mode": "info-chat"},
            ])
            with _BossModel(self._answer("두 번째 후속", done=True)):
                ctxgit.draft_boss_followup(root, store, "sales")
            items = ctxgit.boss_pending_items(store)
            self.assertEqual([i["instruction"] for i in items], ["두 번째 후속"])
            self.assertTrue(items[0]["done"])

    def test_a_follow_up_does_not_overwrite_what_the_user_queued_meanwhile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, store = self._project(tmp)
            ctxgit.dispatch_boss_items(root, store, _BossJobs(), [
                {"branch": "sales", "instruction": "먼저 이거", "mode": "info-chat"},
            ])
            store.append_history("sales", "assistant", "답변")
            # While the branch was working, a new request produced a newer draft.
            ctxgit.upsert_boss_items(store, [ctxgit.new_boss_item("sales", "새 요청에서 온 초안", createdAt="9999")])
            with _BossModel(self._answer("후속")):
                self.assertEqual(ctxgit.draft_boss_followup(root, store, "sales"), {})
            self.assertEqual(ctxgit.boss_pending_items(store)[0]["instruction"], "새 요청에서 온 초안")

    def test_boss_jobs_do_not_notify_as_branch_completions(self) -> None:
        source = Path(ctxgit.__file__).read_text(encoding="utf-8")
        self.assertIn('str(job.get("mode") or "").startswith("boss")', source)


class BossDisplayTextTest(unittest.TestCase):
    """The desk never shows "[... truncated ...]".

    That marker belongs in a prompt, where the model must know something was
    removed. On the board the same string is the thing a person reads, and a
    machine note in the middle of an answer is noise.
    """

    def test_clipping_leaves_no_marker(self) -> None:
        long_text = "문장입니다. " * 200
        clipped = ctxgit.clip_for_display(long_text, 200)
        self.assertNotIn("truncated", clipped)
        self.assertLessEqual(len(clipped), 200)

    def test_short_text_is_untouched(self) -> None:
        self.assertEqual(ctxgit.clip_for_display("짧은 답변", 200), "짧은 답변")

    def test_an_unbroken_run_is_still_clipped(self) -> None:
        # No word boundary to cut at; it must not return the whole string.
        self.assertEqual(len(ctxgit.clip_for_display("x" * 900, 120)), 120)

    def test_the_board_payload_carries_no_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.init(create_initial_branch=False)
            store.create_branch("sales")
            ctxgit.write_boss_config(store, ["sales"])
            store.append_history("sales", "assistant", "아주 긴 답변입니다. " * 600)
            payload = ctxgit.boss_chat_payload(store)
            blob = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("truncated", blob)

    def test_prompts_keep_the_marker(self) -> None:
        # The model still has to be told that content was cut.
        self.assertIn("[... truncated ...]", ctxgit.truncate_middle("가" * 500, 100))
