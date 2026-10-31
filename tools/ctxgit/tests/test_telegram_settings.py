from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402,F401  (must precede loading ctxgit: keeps tests out of the real ~/.ctxgit)

MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("ctxgit_telegram_settings", MODULE_PATH)
ctxgit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ctxgit
assert spec.loader is not None
spec.loader.exec_module(ctxgit)

TOKEN = "123456789:" + "A" * 35
OTHER = "987654321:" + "B" * 35


class TelegramSettingsTest(unittest.TestCase):
    """The settings gear writes the bot token where ctxgit reads it, and only a working one."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.project = self.tmp / "project"
        self.repo.mkdir()
        (self.project / ".ctxgit").mkdir(parents=True)
        # The real repo .env holds the live token; never let a test reach it.
        patcher = unittest.mock.patch.object(ctxgit, "TOOL_REPO_ROOT", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls: list[tuple[str, str, dict]] = []

    def fake_bot(self, fail_on: str = ""):
        def call(token, method, fields=None, timeout=10):
            self.calls.append((token, method, dict(fields or {})))
            if method == fail_on:
                raise ValueError("Bad Request: chat not found")
            return {"username": "test_bot"} if method == "getMe" else {"id": 1}
        return call

    def test_save_writes_repo_env_and_keeps_other_lines(self) -> None:
        env = self.repo / ".env"
        env.write_text("# keep me\nOPENAI_API_KEY=x\nTELEGRAM_BOT_TOKEN=old\nTELEGRAM_CHAT_ID=111\n", encoding="utf-8")
        with unittest.mock.patch.object(ctxgit, "telegram_bot_call", self.fake_bot()):
            result = ctxgit.save_telegram_settings(self.project, TOKEN, "")
        text = env.read_text(encoding="utf-8")
        self.assertIn("# keep me", text)
        self.assertIn("OPENAI_API_KEY=x", text)
        self.assertIn(f"TELEGRAM_BOT_TOKEN={TOKEN}", text)
        self.assertIn("TELEGRAM_CHAT_ID=111", text)  # empty chat id keeps the stored one
        self.assertEqual(text.count("TELEGRAM_BOT_TOKEN="), 1)
        self.assertEqual(result["botUsername"], "test_bot")
        self.assertNotIn(TOKEN, str(result))  # the token is never echoed back
        self.assertEqual(ctxgit.telegram_config_for_root(self.project), (TOKEN, "111"))
        self.assertEqual([m for _, m, _ in self.calls], ["getMe", "getChat"])

    def test_rejected_token_leaves_file_untouched(self) -> None:
        env = self.repo / ".env"
        env.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=111\n", encoding="utf-8")
        before = env.read_text(encoding="utf-8")
        with unittest.mock.patch.object(ctxgit, "telegram_bot_call", self.fake_bot(fail_on="getChat")):
            with self.assertRaises(ValueError):
                ctxgit.save_telegram_settings(self.project, OTHER, "222")
        with self.assertRaises(ValueError):
            ctxgit.save_telegram_settings(self.project, "not-a-token", "")
        self.assertEqual(env.read_text(encoding="utf-8"), before)

    def test_save_goes_where_the_value_is_read_from(self) -> None:
        # A project file overrides the repo file, so writing to the repo file would not take effect.
        (self.repo / ".env").write_text("TELEGRAM_BOT_TOKEN=repo\nTELEGRAM_CHAT_ID=1111\n", encoding="utf-8")
        project_env = self.project / ".ctxgit" / ".env"
        project_env.write_text(f"TELEGRAM_BOT_TOKEN={OTHER}\n", encoding="utf-8")
        with unittest.mock.patch.object(ctxgit, "telegram_bot_call", self.fake_bot()):
            ctxgit.save_telegram_settings(self.project, TOKEN, "2222")
        self.assertIn(f"TELEGRAM_BOT_TOKEN={TOKEN}", project_env.read_text(encoding="utf-8"))
        self.assertEqual(ctxgit.telegram_config_for_root(self.project), (TOKEN, "2222"))

    def test_missing_chat_id_is_an_error_not_a_blank_write(self) -> None:
        with unittest.mock.patch.object(ctxgit, "telegram_bot_call", self.fake_bot()):
            with self.assertRaises(ValueError):
                ctxgit.save_telegram_settings(self.project, TOKEN, "")
        self.assertFalse((self.repo / ".env").exists())


if __name__ == "__main__":
    unittest.main()
