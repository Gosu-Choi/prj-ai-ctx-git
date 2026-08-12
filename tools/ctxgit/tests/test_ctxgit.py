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
                return {"assistant": f"Agent {len(calls)} wrote in workspace."}

            ctxgit.call_provider_prompt = fake_call
            try:
                result = ctxgit.run_sequence_room_turn(root, store, "room", "Collaborate.", run_mode="send")
            finally:
                ctxgit.call_provider_prompt = original_call

            workspace = root / "contexts" / "branches" / "room" / "workspace"
            self.assertEqual([Path(call["kwargs"]["cwd"]) for call in calls], [workspace, workspace])
            self.assertTrue((workspace / "agent-1.md").exists())
            self.assertTrue((workspace / "agent-2.md").exists())
            self.assertFalse((root / "contexts" / "branches" / "writer" / "agent-1.md").exists())
            self.assertIn("Never create, edit, move, or delete files in the source branch directory.", calls[0]["args"][2])
            self.assertIn("contexts/branches/room/workspace", calls[0]["args"][2])
            self.assertIn(
                {"kind": "created-md", "title": "agent-1.md", "path": "contexts/branches/room/workspace/agent-1.md"},
                result["history"][1]["artifacts"],
            )

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
            for index in range(20):
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

    def test_chat_turn_links_created_and_modified_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ctxgit.ContextStore(root)
            store.create_branch("AItrust")
            existing = root / "notes.md"
            existing.write_text("before\n", encoding="utf-8")
            original = ctxgit.call_codex_chat
            try:
                def fake_chat(*_args, **_kwargs):
                    existing.write_text("after\n", encoding="utf-8")
                    (root / "draft.md").write_text("# Draft\n", encoding="utf-8")
                    return {"assistant": "Updated markdown files.", "artifacts": [], "approvalRequests": []}

                ctxgit.call_codex_chat = fake_chat
                payload = ctxgit.run_chat_turn(root, store, "AItrust", "Write markdown.")
            finally:
                ctxgit.call_codex_chat = original

            artifacts = payload["history"][-1]["artifacts"]
            self.assertIn({"kind": "created-md", "title": "draft.md", "path": "draft.md"}, artifacts)
            self.assertIn({"kind": "modified-md", "title": "notes.md", "path": "notes.md"}, artifacts)

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
