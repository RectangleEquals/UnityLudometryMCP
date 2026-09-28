import subprocess
import sys

from conftest import REPO


def test_the_tool_reference_is_current() -> None:
    result = subprocess.run([sys.executable, "tools/tool_reference.py", "--check"], cwd=REPO, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
