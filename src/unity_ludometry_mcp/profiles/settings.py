"""Machine settings (`settings.json` in the profile root): tool install paths, release pins, machine-wide defaults.

Settings are machine-only: nothing game-shaped, no project data, and never an output path (those are facts). On first
run the release pins come from the shipped `rules/pins.json`.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..errors import SETUP_REQUIRED, UlmError
from ..package_data import rules_path
from . import read_json, write_json_atomic

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SHA256 = r"^[0-9a-f]{64}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackagePin(_Model):
    """A pinned release: where to get it and the hash it must have."""

    version: str = Field(min_length=1)
    url: str | None = None
    path: str | None = None
    sha256: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def _one_source(self) -> "PackagePin":
        if (self.url is None) == (self.path is None):
            raise ValueError("a package pin needs exactly one of url and path")
        if self.url is not None and not self.url.startswith("https://"):
            raise ValueError("a package url must be https")
        return self


class Download(_Model):
    url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=SHA256)


class LoaderPin(_Model):
    """A pinned loader release, with one download per architecture (`win_x64`, `win_x86`)."""

    version: str = Field(min_length=1)
    variants: dict[Literal["win_x64", "win_x86"], Download] = Field(min_length=1)


class LoaderPins(_Model):
    bepinex5: LoaderPin | None = None


class Settings(_Model):
    """Every machine setting. Unset optional values are `None` / empty."""

    schema_version: int = SCHEMA_VERSION
    dotnet_path: str | None = None
    dnspy_path: str | None = None
    assetstudio_cli_path: str | None = None
    agent_package: PackagePin | None = None
    dnspy_bridge_package: PackagePin | None = None
    loader_pins: LoaderPins = Field(default_factory=LoaderPins)
    limits: dict[str, Any] = Field(default_factory=dict)
    advisor: dict[str, Any] = Field(default_factory=dict)
    coverage_overrides: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None

    @field_validator("dotnet_path", "dnspy_path", "assetstudio_cli_path")
    @classmethod
    def _absolute(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError("must be an absolute path")
        return value

    def dotnet(self) -> Path:
        """The .NET SDK's `dotnet` executable: the configured path, else the one on PATH. Raises SETUP_REQUIRED."""
        if self.dotnet_path:
            return Path(self.dotnet_path)
        found = shutil.which("dotnet")
        if found:
            return Path(found)
        raise UlmError(
            SETUP_REQUIRED,
            "The .NET SDK wasn't found.",
            "Ask the user to install the .NET SDK (10.0 or newer) or to tell you where dotnet.exe is, then config_set dotnet_path.",
            ["dotnet_path"],
            {"setting": "dotnet_path"},
        )


# Keys config_set accepts: exact keys, and prefixes that take a sub-key (`limits.<key>`, `advisor.<name>`, `ui.<name>`).
EXACT_KEYS = frozenset(
    {"dotnet_path", "dnspy_path", "assetstudio_cli_path", "agent_package", "dnspy_bridge_package", "loader_pins.bepinex5", "coverage_overrides", "log_level"}
)
PREFIX_KEYS = ("limits.", "advisor.", "ui.")
INSTALL_PATH_KEYS = frozenset({"dotnet_path", "dnspy_path", "assetstudio_cli_path"})


def shipped_pins() -> dict[str, Any]:
    raw = json.loads(rules_path("pins.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("$")}


def _key_path(key: str) -> list[str]:
    """`limits.response.max_tokens` → ["limits", "response.max_tokens"]; `loader_pins.bepinex5` → ["loader_pins", "bepinex5"]."""
    head, _, rest = key.partition(".")
    if not rest:
        return [head]
    return [head, rest] if head in ("limits", "advisor", "ui") else [head, *rest.split(".")]


class SettingsStore:
    """Loads and saves `settings.json`. The file is created on the first save."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Settings:
        raw = read_json(self.path)
        if raw is None:
            return Settings.model_validate(shipped_pins())
        try:
            return Settings.model_validate(raw)
        except ValidationError as e:
            raise UlmError(
                SETUP_REQUIRED,
                f"settings.json is damaged: {e.errors()[0]['loc']}: {e.errors()[0]['msg']}",
                "Fix or delete the file (the defaults come back); config_set rewrites it.",
                details={"path": str(self.path)},
            ) from None

    def save(self, settings: Settings) -> None:
        write_json_atomic(self.path, settings.model_dump(mode="json", exclude_none=False))

    def get(self, key: str | None = None) -> Any:
        value: Any = self.load().model_dump(mode="json")
        if key is None:
            return value
        for part in _key_path(key):
            if not isinstance(value, dict) or part not in value:
                raise KeyError(key)
            value = value[part]
        return value

    def set(self, key: str, value: Any) -> tuple[Any, Any]:
        """Sets one key and saves; returns (previous, new). Raises KeyError for an unknown key, ValueError for a bad value."""
        if key.startswith("paths."):
            raise ValueError("Output paths aren't machine settings: they're target or project facts (paths_set).")
        if key not in EXACT_KEYS and not any(key.startswith(p) and len(key) > len(p) for p in PREFIX_KEYS):
            raise KeyError(key)
        if key in INSTALL_PATH_KEYS and value is not None:
            path = Path(str(value))
            if not path.is_absolute() or not path.exists():
                raise ValueError(f"{key} must be an absolute path that exists.")
        data = self.load().model_dump(mode="json")
        try:
            previous = self.get(key)
        except KeyError:
            previous = None
        head, _, rest = key.partition(".")
        if head in ("limits", "advisor", "ui"):
            if value is None:
                data[head].pop(rest, None)
            else:
                data[head][rest] = value
        elif rest:
            data[head][rest] = value
        else:
            data[head] = value
        try:
            settings = Settings.model_validate(data)
        except ValidationError as e:
            first = e.errors()[0]
            raise ValueError(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from None
        self.save(settings)
        log.info("Setting %s changed", key)
        try:
            return previous, self.get(key)
        except KeyError:  # cleared
            return previous, None
