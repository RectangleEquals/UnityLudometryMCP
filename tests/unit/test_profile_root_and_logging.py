import logging
import pathlib

import pytest

from unity_ludometry_mcp.logging_setup import configure_logging
from unity_ludometry_mcp.profiles.paths import default_profile_root, resolve_profile_root


def test_the_default_profile_root_is_the_local_app_data_folder() -> None:
    root = resolve_profile_root({})
    assert root.source == "default"
    assert root.path == default_profile_root()
    assert root.path.name == "UnityLudometryMCP"
    assert "roaming" not in str(root.path).lower()


def test_ulm_home_overrides_the_profile_root(tmp_path: pathlib.Path) -> None:
    root = resolve_profile_root({"ULM_HOME": f"  {tmp_path}  "})
    assert root.source == "ULM_HOME"
    assert root.path == tmp_path
    assert root.exists
    assert not resolve_profile_root({"ULM_HOME": str(tmp_path / "missing")}).exists
    assert resolve_profile_root({"ULM_HOME": "   "}).source == "default"


def test_a_relative_ulm_home_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        resolve_profile_root({"ULM_HOME": "relative/profile"})


@pytest.mark.parametrize(("value", "level"), [("", logging.INFO), ("debug", logging.DEBUG), (" Warning ", logging.WARNING), ("ERROR", logging.ERROR)])
def test_log_level_comes_from_the_environment(value: str, level: int) -> None:
    assert configure_logging({"ULM_LOG_LEVEL": value}).level == level


def test_logs_go_to_stderr_and_an_unknown_level_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    log = configure_logging({"ULM_LOG_LEVEL": "loud"})
    assert log.level == logging.INFO
    assert [type(h).__name__ for h in log.handlers] == ["StreamHandler", "ClientLogHandler"]
    log.info("hello")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Ignoring ULM_LOG_LEVEL='LOUD'" in captured.err
    assert "hello" in captured.err
