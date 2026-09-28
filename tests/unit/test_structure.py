"""The package layout: every package exists and imports, and every tool group module registers tools once it has any."""

import importlib
import pkgutil
import tomllib

import pytest
from fastmcp import FastMCP

import unity_ludometry_mcp
from conftest import REPO
from unity_ludometry_mcp.server import TOOL_MODULES

PACKAGES = [
    "tools",
    "profiles",
    "data",
    "data.importers",
    "data.schema",
    "pipeline",
    "research",
    "advisor",
    "providers",
    "providers.catalog_parser",
    "enrich",
    "runtime",
    "mods",
    "knowledge",
    "limits",
    "protocol",
    "consent",
]
MODULES = ["server", "envelope", "errors", "tasks", "events", "budget", "logging_setup", "__main__"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_exists(name: str) -> None:
    module = importlib.import_module(f"unity_ludometry_mcp.{name}")
    assert module.__path__, f"{name} is not a package"


@pytest.mark.parametrize("name", MODULES)
def test_module_exists(name: str) -> None:
    importlib.import_module(f"unity_ludometry_mcp.{name}")


def test_every_module_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(unity_ludometry_mcp.__path__, "unity_ludometry_mcp.")]
    assert len(names) > 100
    for name in names:
        importlib.import_module(name)


def test_every_tool_group_module_is_listed() -> None:
    on_disk = {m.name for m in pkgutil.iter_modules(importlib.import_module("unity_ludometry_mcp.tools").__path__)}
    assert on_disk == set(TOOL_MODULES)


@pytest.mark.parametrize("name", TOOL_MODULES)
async def test_tool_group_registers_tools(name: str) -> None:
    module = importlib.import_module(f"unity_ludometry_mcp.tools.{name}")
    register = getattr(module, "register", None)
    if register is None:
        pytest.skip(f"tools.{name} has no tools yet")
    app: FastMCP = FastMCP("structure-test")
    register(app)
    assert await app.list_tools(), f"tools.{name}.register added no tools"


def test_package_data_directories_exist() -> None:
    for relative in ["rules/guides", "rules/crossexam", "rules/reconcile", "templates", "protocol/schema"]:
        assert (REPO / relative).is_dir(), relative
    for name in ["middleware", "serializers", "assemblies", "research", "intents", "coverage", "advisor", "limits", "pins"]:
        assert (REPO / "rules" / f"{name}.json").is_file(), name


def test_version_matches_pyproject() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == unity_ludometry_mcp.__version__
    assert project["scripts"]["unity-ludometry-mcp"] == "unity_ludometry_mcp.__main__:main"
