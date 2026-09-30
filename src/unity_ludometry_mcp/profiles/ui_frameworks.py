"""UI frameworks and input facts: what a game can use (from its files) and what it uses (static usage merged with the agent).

Fact keys (target scope):

- `ui.frameworks_available`: `{ugui, uiToolkit, tmp, imgui: bool}` from the assemblies present and the Unity version
  (runtime UI Toolkit needs Unity 2021.2+).
- `input.systems_present`: the input systems present, `["inputManager", "inputSystem"]` or a subset.
- `ui.frameworks_used`: per framework `{classification, source, screens}`, merged from static usage and the agent's
  `ui.frameworks` reports by `merge_frameworks_used`.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FRAMEWORKS_AVAILABLE = "ui.frameworks_available"
FRAMEWORKS_USED = "ui.frameworks_used"
INPUT_SYSTEMS_PRESENT = "input.systems_present"

Classification = Literal["primary", "secondary", "unused", "unavailable"]
CLASSIFIED = ("ugui", "uiToolkit", "imgui")
_RANK: dict[str, int] = {"unavailable": 0, "unused": 1, "secondary": 2, "primary": 3}

_ASSEMBLIES = {
    "ugui": "UnityEngine.UI",
    "uiToolkit": "UnityEngine.UIElementsModule",
    "tmp": "Unity.TextMeshPro",
    "imgui": "UnityEngine.IMGUIModule",
}


def _unity_at_least(version: str, major: int, minor: int) -> bool:
    match = re.match(r"(\d+)\.(\d+)", version)
    return match is not None and (int(match[1]), int(match[2])) >= (major, minor)


def _names(assemblies: Iterable[str]) -> set[str]:
    return {name.removesuffix(".dll") for name in assemblies}


def frameworks_available(assemblies: Iterable[str], unity_version: str) -> dict[str, bool]:
    """`ui.frameworks_available` from the assembly names in the game's Managed folder and its Unity version.

    Unity 2017.1 and older ship IMGUI inside UnityEngine.dll (no module assembly); a known version counts it as available.
    """
    names = _names(assemblies)
    return {
        "ugui": _ASSEMBLIES["ugui"] in names,
        "uiToolkit": _ASSEMBLIES["uiToolkit"] in names and _unity_at_least(unity_version, 2021, 2),
        "tmp": _ASSEMBLIES["tmp"] in names,
        "imgui": _ASSEMBLIES["imgui"] in names or (bool(unity_version) and not _unity_at_least(unity_version, 2017, 2)),
    }


def input_systems_present(assemblies: Iterable[str]) -> list[str]:
    """`input.systems_present`: the Input Manager is always there; the Input System package when its assembly is."""
    return ["inputManager", "inputSystem"] if "Unity.InputSystem" in _names(assemblies) else ["inputManager"]


@dataclass(frozen=True)
class RuntimeSample:
    """One `ui.frameworks` report and the screen it was taken on (a scene or a description of what was shown)."""

    classification: Mapping[str, str]
    screen: str


def merge_frameworks_used(static_usage: Mapping[str, str], samples: Sequence[RuntimeSample]) -> dict[str, dict[str, Any]]:
    """`ui.frameworks_used`: static usage merged with the agent's reports.

    - A framework the agent reports `unavailable` is unavailable (the game can't load it, whatever the code references).
    - What the agent saw in use (`primary` or `secondary` on some screen) wins, with its best rank and the screens it was
      seen on: the report describes the running game.
    - Otherwise static usage stands: a framework unused on the screens sampled may still be used on others.
    - With neither, the agent's `unused` is kept; a framework nobody reported is left out.
    """
    merged: dict[str, dict[str, Any]] = {}
    for framework in CLASSIFIED:
        seen = [(c, s.screen) for s in samples if (c := s.classification.get(framework)) is not None and c in _RANK]
        runtime = max((c for c, _ in seen), key=lambda c: _RANK[c], default=None)
        static = static_usage.get(framework)
        if any(c == "unavailable" for c, _ in seen):
            merged[framework] = {"classification": "unavailable", "source": "runtime", "screens": []}
        elif runtime in ("primary", "secondary"):
            screens = sorted({screen for c, screen in seen if c in ("primary", "secondary")})
            merged[framework] = {"classification": runtime, "source": "runtime", "screens": screens}
        elif static in _RANK:
            merged[framework] = {"classification": static, "source": "static", "screens": []}
        elif runtime == "unused":
            merged[framework] = {"classification": "unused", "source": "runtime", "screens": sorted({screen for _, screen in seen})}
    return merged
