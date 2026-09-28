"""Where ULM keeps its data: the profile root, and (as the profile store grows) path resolution and validation."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import platformdirs

APP_DIR_NAME = "UnityLudometryMCP"
HOME_ENV = "ULM_HOME"


@dataclass(frozen=True)
class ProfileRoot:
    """The profile root and where its location came from."""

    path: Path
    source: Literal["ULM_HOME", "default"]

    @property
    def exists(self) -> bool:
        return self.path.is_dir()


def default_profile_root() -> Path:
    """The per-user default: `%LOCALAPPDATA%\\UnityLudometryMCP` on Windows (the platform's local data directory elsewhere)."""
    return Path(platformdirs.user_data_dir(APP_DIR_NAME, appauthor=False, roaming=False))


def resolve_profile_root(environ: Mapping[str, str] | None = None) -> ProfileRoot:
    """The profile root for this run. `ULM_HOME` overrides the default for one run and is never written back.

    Raises `ValueError` if `ULM_HOME` is set but isn't an absolute path.
    """
    env = os.environ if environ is None else environ
    override = env.get(HOME_ENV, "").strip()
    if not override:
        return ProfileRoot(default_profile_root(), "default")

    path = Path(override).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{HOME_ENV} must be an absolute path, got {override!r}.")
    return ProfileRoot(path, "ULM_HOME")
