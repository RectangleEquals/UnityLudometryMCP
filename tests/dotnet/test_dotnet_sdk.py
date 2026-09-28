"""Tests that build C# with the .NET SDK (templates, snippets, patches) live here, marked `dotnet`.

Run them with `pytest -m dotnet`; they're excluded from the default run.
"""

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.dotnet


def test_a_dotnet_sdk_is_installed() -> None:
    dotnet = shutil.which("dotnet")
    assert dotnet, "the .NET SDK is required to build snippets, patches and mods"
    sdks = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True, check=True, timeout=120).stdout
    assert sdks.strip(), "dotnet is installed but has no SDK"
