import json
import os
import pathlib
import sys
from typing import Any

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PROTOCOL = REPO / "protocol"
TEST_SETTINGS_ENV = "ULM_TEST_SETTINGS"

# The generators live outside the package; tests import them for freshness checks.
sys.path.insert(0, str(PROTOCOL / "codegen"))


@pytest.fixture(autouse=True)
def _isolated_profile_root(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Every test gets its own profile root, so no test ever reads or writes the user's real profile."""
    root = tmp_path_factory.mktemp("profile-root")
    monkeypatch.setenv("ULM_HOME", str(root))
    return root


@pytest.fixture(scope="session")
def real_test_settings() -> dict[str, Any]:
    """Settings for `integration_real` tests: a JSON file outside the repository, named by ULM_TEST_SETTINGS.

    Tests that use this fixture skip when the variable isn't set.
    """
    path = os.environ.get(TEST_SETTINGS_ENV)
    if not path:
        pytest.skip(f"{TEST_SETTINGS_ENV} is not set")
    settings: dict[str, Any] = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return settings
