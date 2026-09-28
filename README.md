# UnityLudometryMCP

A local [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that helps you understand Unity games
and build mods for them. It combines optional static-analysis tools, online research and a runtime agent inside the game
([UnityRuntimeAnalysisAgent](https://github.com/RectangleEquals/UnityRuntimeAnalysisAgent)) into one knowledge base that
your AI assistant can query and act on, with your consent at every step that changes anything.

> **Status: pre-release (v0.1 in development).** The MCP server runs and can be registered with your client, but it
> offers only `server_status` so far. The rest of the orchestrator is being built.

## What's here now
- The MCP server `unity-ludometry-mcp` (stdio) with the `server_status` tool.
- [`protocol/`](protocol/README.md): the schema-first protocol spoken between the orchestrator and the agent: JSON Schemas
  for every method, event and exchanged file, golden fixtures, and the zero-dependency C# package
  `UnityLudometry.Protocol` (with message types generated from the schemas) that the agent uses.
- `src/unity_ludometry_mcp/`: the Python orchestrator: the protocol layer (models generated from the schemas, strict
  JSON, framing, envelopes, named-pipe/TCP transports), agent discovery, the agent client, and the package layout the
  rest of the orchestrator grows into.
- [`docs/`](docs/README.md): documentation.

## Requirements
Windows, Python 3.13 with [uv](https://docs.astral.sh/uv/), and the [.NET SDK](https://dotnet.microsoft.com/download)
(10.0 or newer). Later, optionally: dnSpyEx and the AssetStudio command-line tool, for static analysis.

## Install and register
There are no releases yet; run the server from a clone and register it with your MCP client as `unity-ludometry-mcp`.
In Claude Code:

```
git clone https://github.com/RectangleEquals/UnityLudometryMCP
cd UnityLudometryMCP
uv sync
claude mcp add unity-ludometry-mcp -- uv run --directory <path to your clone> unity-ludometry-mcp
```

[Getting started](docs/getting-started.md) has the JSON form for other clients, what gets written where (the profile
root, otherwise only folders you choose; today nothing at all) and how to remove everything.
[Configuration](docs/configuration.md) lists the environment variables.

## Building and testing
See [CONTRIBUTING](docs/CONTRIBUTING.md). In short:

```
uv sync --group dev
uv run pytest
```

## About the use of AI in this project
This section is here so you can decide for yourself, with accurate information.

**How this project is being made.** The design and implementation are produced with the help of an AI coding assistant
(Anthropic's Claude), working under the direct supervision of a human developer. In practice:
- The human decides what the project is for, sets every requirement and constraint, and chooses between the options the
  AI proposes.
- The AI drafts code and documentation within those requirements, one small, reviewable step at a time.
- **The human reviews every step** before it becomes part of the project. Every commit in this repository is made by the
  human, not by the AI.
- Behaviour is checked by automated tests (for the protocol: schema validation and golden fixtures replayed by both
  sides) and, as the project grows, by running it against real Unity games.

**How this project uses AI when you run it.** UnityLudometryMCP is an MCP server: it contains no AI model and never
contacts an AI service by itself. It offers tools to the AI assistant *you* connect it to (for example Claude Code), and
that assistant decides which tools to call. You stay in control:
- Anything that changes something (installing the in-game agent, raising its permission level, modifying a running game,
  writing files) needs your explicit consent, and every installation is recorded so it can be undone exactly.
- The in-game agent starts read-only, lists every action in its overlay, and has an **E-STOP** that stops all automated
  activity immediately.
- Files are written only to locations you choose. Online research is done by your assistant's own web tools, and its
  results are treated as unverified until the game confirms them.

If you have questions or concerns about any of this, please open an issue.

## License
MIT. See [LICENSE](LICENSE).
