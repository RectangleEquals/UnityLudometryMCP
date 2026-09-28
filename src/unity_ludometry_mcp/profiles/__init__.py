"""Profile store: settings, facts with provenance, manifests, ledgers, paths and setup questions.

Every file the store writes goes through `write_json_atomic` (temp file + replace), so a crash never leaves a half-written
file behind.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    """Writes JSON to `path` atomically (a temp file in the same folder, then `os.replace`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any:
    """Reads a JSON file; `None` if it doesn't exist."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
