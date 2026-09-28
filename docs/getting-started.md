# Getting started

UnityLudometryMCP is an MCP server. Your MCP client (for example Claude Code) starts it and talks to it over stdio, so
you register it once and don't run it by hand.

> **Pre-release.** The server currently offers one tool, `server_status`. The rest of the orchestrator is being built.

## Requirements

- Windows.
- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- The [.NET SDK](https://dotnet.microsoft.com/download) (10.0 or newer). The server will use it to build code snippets,
  live patches and mods.

## Install

There are no releases yet, so run it from a clone:

```
git clone https://github.com/RectangleEquals/UnityLudometryMCP
cd UnityLudometryMCP
uv sync
uv run unity-ludometry-mcp --version
```

Once releases exist, `uv tool install` will install the `unity-ludometry-mcp` command directly.

## Register with your MCP client

The server's name is `unity-ludometry-mcp`. In Claude Code:

```
claude mcp add unity-ludometry-mcp -- uv run --directory <path to your clone> unity-ludometry-mcp
```

Other clients take a JSON entry like this one (the exact file depends on the client):

```json
{
  "mcpServers": {
    "unity-ludometry-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "<path to your clone>", "unity-ludometry-mcp"]
    }
  }
}
```

Then ask your assistant to call `server_status`. It reports the server's version, the agent protocol version, where the
server keeps its data, and what your client supports.

## What gets written where

All of the server's own data will live in one folder, the **profile root**:
`%LOCALAPPDATA%\UnityLudometryMCP` by default (see [configuration](configuration.md) to change it). Anything else it
writes goes only to locations you choose.

Today the server writes nothing: `server_status` only reports where the profile root would be. To remove the server,
unregister it from your client (`claude mcp remove unity-ludometry-mcp`), then delete the clone and, if it exists, the
profile root.
