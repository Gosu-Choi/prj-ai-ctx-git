"""Windows compatibility guards.

ctxgit is developed on macOS, so a Windows-only regression is invisible until an
employee's first run. These tests pin the Windows paths down from the outside:
what each subprocess decodes, how a configured command splits, and how a file is
replaced while something else holds it.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "ctxgit.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("ctxgit_windows_compat", MODULE_PATH)
ctxgit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ctxgit  # dataclasses look the module up while it loads
assert spec.loader is not None
spec.loader.exec_module(ctxgit)


def _subprocess_calls(source: str) -> list[tuple[int, str]]:
    calls = []
    for match in re.finditer(r"subprocess\.(run|Popen|check_output)\(", source):
        start = source.index("(", match.start())
        depth, end = 0, start
        while True:
            char = source[end]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        calls.append((source.count("\n", 0, match.start()) + 1, source[start:end]))
    return calls


class SubprocessEncodingTest(unittest.TestCase):
    def test_every_text_mode_subprocess_names_its_encoding(self) -> None:
        # Without an explicit encoding, text mode decodes with the locale code page:
        # cp949 on Korean Windows, which fails on UTF-8 git subjects and prompts.
        calls = _subprocess_calls(MODULE_PATH.read_text(encoding="utf-8"))
        text_calls = [(line, body) for line, body in calls if "text=True" in body]
        self.assertTrue(text_calls, "expected text-mode subprocess calls to inspect")
        missing = [line for line, body in text_calls if "encoding=" not in body]
        self.assertEqual(missing, [], f"text=True without encoding at lines {missing}")


class SplitCommandTest(unittest.TestCase):
    def test_windows_path_keeps_its_backslashes(self) -> None:
        with unittest.mock.patch.object(ctxgit.os, "name", "nt"):
            self.assertEqual(
                ctxgit.split_command(r"C:\Users\me\.local\bin\claude.exe"),
                [r"C:\Users\me\.local\bin\claude.exe"],
            )
            self.assertEqual(
                ctxgit.split_command(r'"C:\Program Files\Codex\codex.exe" --flag'),
                [r"C:\Program Files\Codex\codex.exe", "--flag"],
            )

    def test_posix_split_is_unchanged(self) -> None:
        with unittest.mock.patch.object(ctxgit.os, "name", "posix"):
            self.assertEqual(ctxgit.split_command("npx -y 'a b'"), ["npx", "-y", "a b"])


class ReplaceFileTest(unittest.TestCase):
    def test_windows_retries_a_momentary_lock(self) -> None:
        real_replace = ctxgit.os.replace
        attempts = []

        def flaky(source, target):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError("in use")
            real_replace(source, target)

        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "a.tmp", Path(tmp) / "a.json"
            source.write_text("new", encoding="utf-8")
            target.write_text("old", encoding="utf-8")
            with unittest.mock.patch.object(ctxgit.os, "name", "nt"), \
                    unittest.mock.patch.object(ctxgit.os, "replace", flaky), \
                    unittest.mock.patch.object(ctxgit.time, "sleep"):
                ctxgit.replace_file(source, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(len(attempts), 3)

    def test_posix_does_not_swallow_errors(self) -> None:
        with unittest.mock.patch.object(ctxgit.os, "name", "posix"), \
                unittest.mock.patch.object(ctxgit.os, "replace", side_effect=PermissionError("x")):
            with self.assertRaises(PermissionError):
                ctxgit.replace_file("a", "b")


class PowerShellPickerTest(unittest.TestCase):
    def test_initial_directory_travels_outside_the_script_text(self) -> None:
        completed = unittest.mock.Mock(returncode=0, stdout="C:\\작업\\프로젝트\n", stderr="")
        with unittest.mock.patch.object(ctxgit.subprocess, "run", return_value=completed) as run:
            chosen = ctxgit.choose_directory_with_powershell(Path("C:/start here"))
        self.assertEqual(chosen, "C:\\작업\\프로젝트")
        argv = run.call_args.args[0]
        # -Command must be last with the script as its value; anything after it
        # would be appended to the script and executed.
        self.assertEqual(argv[-2], "-Command")
        self.assertIn("$env:CTXGIT_DIALOG_INITIAL", argv[-1])
        self.assertIn("OutputEncoding", argv[-1])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["env"]["CTXGIT_DIALOG_INITIAL"], str(Path("C:/start here")))


class ExternalMcpServerTest(unittest.TestCase):
    """`ctxgit mcp-server` runs an extension's external server (Slack: `npx`)."""

    def _ext(self):
        ext = unittest.mock.Mock()
        return ext, {"slack": {"command": "npx", "args": ["-y", "slack-mcp-server"], "env": {"T": "x"}}}

    def test_windows_resolves_pathext_and_stays_attached(self) -> None:
        ext, servers = self._ext()
        with unittest.mock.patch.object(ctxgit.os, "name", "nt"), \
                unittest.mock.patch.object(ctxgit.extensions, "get_extension", return_value=ext), \
                unittest.mock.patch.object(ctxgit.extensions, "mcp_servers", return_value=servers), \
                unittest.mock.patch.object(ctxgit.shutil, "which", return_value=r"C:\node\npx.cmd"), \
                unittest.mock.patch.object(ctxgit.subprocess, "call", return_value=3) as call, \
                unittest.mock.patch.object(ctxgit.os, "execvpe") as execvpe:
            code = ctxgit.run_extension_mcp_server("slack", "slack")
        execvpe.assert_not_called()
        self.assertEqual(code, 3)
        self.assertEqual(call.call_args.args[0], [r"C:\node\npx.cmd", "-y", "slack-mcp-server"])
        self.assertEqual(call.call_args.kwargs["env"]["T"], "x")

    def test_posix_still_execs(self) -> None:
        ext, servers = self._ext()
        with unittest.mock.patch.object(ctxgit.os, "name", "posix"), \
                unittest.mock.patch.object(ctxgit.extensions, "get_extension", return_value=ext), \
                unittest.mock.patch.object(ctxgit.extensions, "mcp_servers", return_value=servers), \
                unittest.mock.patch.object(ctxgit.subprocess, "call") as call, \
                unittest.mock.patch.object(ctxgit.os, "execvpe") as execvpe:
            ctxgit.run_extension_mcp_server("slack", "slack")
        call.assert_not_called()
        self.assertEqual(execvpe.call_args.args[0], "npx")


if __name__ == "__main__":
    unittest.main()
