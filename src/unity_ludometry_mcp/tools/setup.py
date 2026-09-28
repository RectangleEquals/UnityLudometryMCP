"""Setup questions and answers, machine configuration, and guides."""

import shutil
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, JsonValue

from ..errors import INVALID_ARGUMENT, NOT_FOUND, UlmError
from ..profiles.settings import EXACT_KEYS, PREFIX_KEYS
from . import ToolCall, register_tools, ulm_tool

SettingKey = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "A machine setting: dotnet_path, dnspy_path, assetstudio_cli_path, agent_package, dnspy_bridge_package, "
            "loader_pins.bepinex5, coverage_overrides, log_level, or limits.<limit>, advisor.<name>, ui.<name>."
        ),
    ),
]


@ulm_tool(group="core", title="Get machine settings", read_only=True, idempotent=True)
def config_get(call: ToolCall, key: Annotated[str | None, Field(description="One setting; all when omitted.")] = None) -> dict[str, Any]:
    """The machine settings (settings.json in the profile root): tool install paths, release pins and machine-wide
    defaults. Output folders aren't settings; see paths_get. Also shows the .NET SDK found on this machine."""
    settings = call.session.store.settings
    try:
        value = settings.get(key)
    except KeyError:
        raise UlmError(NOT_FOUND, f"No setting {key!r}.", "Call config_get without a key to see them all.") from None
    detected = shutil.which("dotnet")
    return {"key": key, "value": value, "file": str(settings.path), "saved": settings.path.is_file(), "detected": {"dotnet": detected}}


@ulm_tool(group="core", title="Change a machine setting", destructive=True, idempotent=True)
def config_set(
    call: ToolCall,
    key: SettingKey,
    value: Annotated[JsonValue, Field(description="The new value; null clears it.")],
) -> dict[str, Any]:
    """Change one machine setting. Install paths are only what the user tells you (never guess one); output folders are
    set with paths_set instead. Limits set here are this machine's defaults for every game."""
    clamped_to = None
    if key.startswith("limits.") and value is not None:
        limit = key.removeprefix("limits.")
        try:
            definition = call.session.limits.get(limit)
            effective, clamped = definition.validate(value)
            clamped_to = effective if clamped else None
        except KeyError:
            raise UlmError(NOT_FOUND, f"No limit {limit!r}.", "limits are listed in rules/limits.json.") from None
        except ValueError as e:
            raise UlmError(INVALID_ARGUMENT, str(e), "Check the value.") from None
    try:
        previous, new = call.session.store.settings.set(key, value)
    except KeyError:
        known = ", ".join([*sorted(EXACT_KEYS), *(p + "<name>" for p in PREFIX_KEYS)])
        raise UlmError(NOT_FOUND, f"No setting {key!r}.", f"Settings: {known}.") from None
    except ValueError as e:
        raise UlmError(INVALID_ARGUMENT, str(e), "Check the value.") from None
    out: dict[str, Any] = {"key": key, "previous": previous, "value": new}
    if clamped_to is not None:
        out["effective"] = clamped_to
        out["note"] = "Outside the limit's hard bounds: this value is used as the effective one."
    return out


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [config_get, config_set])
