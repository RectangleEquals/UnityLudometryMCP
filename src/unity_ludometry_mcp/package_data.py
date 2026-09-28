"""Files shipped with the package: `rules/`, `templates/` and the protocol schemas.

In an installed wheel they live under `unity_ludometry_mcp/_data/`; in a clone they're read from the repository root.
"""

from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_REPO = _PACKAGE.parents[1]


def data_root() -> Path:
    """The folder that holds `rules/`, `templates/` and `protocol/schema/`."""
    installed = _PACKAGE / "_data"
    return installed if installed.is_dir() else _REPO


def rules_path(*parts: str) -> Path:
    """A path below the shipped `rules/` folder."""
    return data_root().joinpath("rules", *parts)
