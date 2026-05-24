from __future__ import annotations

import importlib.util
import contextlib
import io
import json
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
            self.assertIn("Cross-Branch Synthesis", view)

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
            self.assertIn("Kind: `research`", path.read_text())

    def test_invalid_branch_id_exits(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ctxgit.validate_id("../bad", "branch")


if __name__ == "__main__":
    unittest.main()
