"""The runtime never imports the fuzzy matcher — a guard on Tier 1 determinism.

Fuzzy matching is allowed only in the offline proposal script. If any runtime module
reached ``rapidfuzz`` (directly, or by importing the script), a probabilistic join could
run beneath a verified claim. This is checked in a clean subprocess so an unrelated test
that imported ``rapidfuzz`` earlier in the session cannot mask a real leak.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# The src/ layout root, so the clean subprocess can import the runtime package.
SRC = Path(__file__).resolve().parents[2]


def test_importing_the_runtime_does_not_import_rapidfuzz() -> None:
    probe = (
        "import sys; "
        "import interconnection_agent.poi; "
        "import interconnection_agent.ingest; "
        "import interconnection_agent.cli; "
        "assert 'rapidfuzz' not in sys.modules, "
        "'runtime code imported the offline fuzzy matcher'"
    )
    pythonpath = os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])
    env = {**os.environ, "PYTHONPATH": pythonpath}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
