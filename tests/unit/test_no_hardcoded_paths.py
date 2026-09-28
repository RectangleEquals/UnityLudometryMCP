"""No machine path is hardcoded in the package: every folder comes from platformdirs, ULM_HOME or the user."""

import ast
import re

from conftest import REPO

PATTERN = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|%LOCALAPPDATA%|%APPDATA%|\\AppData\\|/AppData/", re.IGNORECASE)


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def test_no_drive_letters_or_windows_profile_folders_in_code() -> None:
    offenders = []
    for path in sorted((REPO / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and PATTERN.search(node.value):
                offenders.append(f"{path.relative_to(REPO)}:{node.lineno}: {node.value[:60]!r}")
    assert offenders == []


def test_the_check_catches_hardcoded_paths() -> None:
    backslashed = "X:" + "\\Example\\Games"
    for sample in [backslashed, "X:/Example/out", "%LOCALAPPDATA%\\x", "X:/Example/AppData/Local"]:
        assert PATTERN.search(sample), sample
    for sample in ["https://example.invalid/a", "limits.response.max_tokens", "ulm://guide/{topic}"]:
        assert not PATTERN.search(sample), sample
