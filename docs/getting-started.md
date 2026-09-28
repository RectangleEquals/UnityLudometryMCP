# Getting started

UnityLudometryMCP is an MCP server. Your MCP client (for example Claude Code) starts it and talks to it over stdio, so
you register it once and don't run it by hand.

> **Pre-release.** The server currently offers its basic tools: status, settings, tool groups, tasks, events, and
> managing ULM's own records of games, projects and output folders. Opening a game for analysis comes next. The
> [tool reference](tools.md) lists what's there.

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
server keeps its data, what your client supports, and which tool groups are listed.

## How the server talks to your assistant

- Every tool returns the same shape: `{ok, data}` or `{ok: false, error: {code, message, hint}}`, plus, when there are
  any, `notices` (things that happened in the game since the last call), `advisories` (questions for you),
  `redactions` (parts left out, and where to find them) and `task_id` (for work that runs in the background).
- Anything that changes something asks for your approval first. If your client supports it, the server asks you
  directly in a dialog; otherwise your assistant asks you in the chat, and must not answer for you.
- Long operations run as tasks: the tool returns a `task_id` at once, and `task_wait` returns the result.

## What gets written where

All of the server's own data will live in one folder, the **profile root**:
`%LOCALAPPDATA%\UnityLudometryMCP` by default (see [configuration](configuration.md) to change it). Anything else it
writes goes only to locations you choose.

Inside the profile root the server keeps its log (`logs\`), its settings (`settings.json`, once you change one) and a
folder per game and project (`targets\`). Outside it, it writes only to folders you chose ([configuration](configuration.md)
explains them). To remove the server, unregister it from your client (`claude mcp remove unity-ludometry-mcp`), then
delete the clone and the profile root. (Once ULM can install things into a game, remove those from each game first:
the profile holds the records needed to restore it.)
