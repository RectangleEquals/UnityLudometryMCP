"""Regenerates everything generated in this repository (or, with --check, verifies it's current).

    uv run python tools/codegen.py [--check]

Runs the protocol generators (C# and Python models from protocol/schema) and the tool reference (docs/tools.md).
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STEPS = [
    ["protocol/codegen/csharp.py"],
    ["protocol/codegen/python.py"],
    ["tools/tool_reference.py"],
]


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    if argv and not check:
        print(__doc__)
        return 2
    failed = False
    for step in STEPS:
        result = subprocess.run([sys.executable, *step, *(["--check"] if check else [])], cwd=REPO, check=False)
        failed |= result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
