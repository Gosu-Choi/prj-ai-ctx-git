from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402

MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("ctxgit_home_guard", MODULE_PATH)
ctxgit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ctxgit
assert spec.loader is not None
spec.loader.exec_module(ctxgit)


class HomeGuardTest(unittest.TestCase):
    def test_global_settings_live_in_the_throwaway_home(self) -> None:
        path = ctxgit.global_settings_path()
        self.assertTrue(path.is_relative_to(_home_guard.TEST_HOME), path)
        self.assertFalse(path.is_relative_to(_home_guard._REAL_HOME / ".ctxgit"), path)

    def test_remember_opened_project_writes_only_the_throwaway_home(self) -> None:
        before = _home_guard._fingerprint(_home_guard._REAL_SETTINGS)
        ctxgit.remember_opened_project(_home_guard.TEST_HOME)
        self.assertIn(str(_home_guard.TEST_HOME.resolve()),
                      ctxgit.read_global_settings().get("openedProjects", []))
        self.assertEqual(_home_guard._fingerprint(_home_guard._REAL_SETTINGS), before)


if __name__ == "__main__":
    unittest.main()
