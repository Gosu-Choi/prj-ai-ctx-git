"""Keep the test run out of the real home directory.

ctxgit keeps machine-wide settings in ``~/.ctxgit/settings.json``: the list of
opened projects (the only list the Telegram remote can reach), extension
toggles, and output switches. Tests that open projects or flip toggles write
there, so running the suite used to overwrite the user's own settings and change
how the live server behaved. Every test module imports this first; it points
HOME at a throwaway directory before ctxgit is loaded and fails loudly at exit
if the real settings file changed anyway.

Git still reads the real global config, so commits made by tests keep the
user's identity without the suite writing anywhere under the real home.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import sys
import tempfile
from pathlib import Path

_REAL_HOME = Path(os.environ.get("HOME") or Path.home())
_REAL_SETTINGS = _REAL_HOME / ".ctxgit" / "settings.json"


def _fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


if not os.environ.get("CTXGIT_TEST_HOME"):
    _before = _fingerprint(_REAL_SETTINGS)
    fake_home = tempfile.mkdtemp(prefix="ctxgit-test-home-")
    real_gitconfig = _REAL_HOME / ".gitconfig"
    if real_gitconfig.exists() and not os.environ.get("GIT_CONFIG_GLOBAL"):
        os.environ["GIT_CONFIG_GLOBAL"] = str(real_gitconfig)
    os.environ["HOME"] = fake_home
    os.environ["USERPROFILE"] = fake_home
    os.environ["CTXGIT_TEST_HOME"] = fake_home

    def _check_real_settings() -> None:
        if _fingerprint(_REAL_SETTINGS) != _before:
            sys.stderr.write(
                f"\nctxgit tests changed the real {_REAL_SETTINGS}; "
                "a test reached the user's home despite the guard.\n"
            )
            os._exit(1)

    atexit.register(_check_real_settings)

TEST_HOME = Path(os.environ["CTXGIT_TEST_HOME"])
