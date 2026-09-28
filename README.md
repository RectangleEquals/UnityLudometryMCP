# UnityLudometryMCP

A local [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that helps you understand Unity games
and build mods for them. It combines optional static-analysis tools, online research and a runtime agent inside the game
([UnityRuntimeAnalysisAgent](https://github.com/RectangleEquals/UnityRuntimeAnalysisAgent)) into one knowledge base that
your AI assistant can query and act on, with your consent at every step that changes anything.

> **Status: pre-release (v0.1 in development).** The orchestrator itself is under construction. What exists today is the
> shared **protocol** between the orchestrator and the in-game agent: [`protocol/`](protocol/README.md).

## What's here now
- [`protocol/`](protocol/README.md): the schema-first protocol spoken between the orchestrator and the agent: JSON Schemas
  for every method, event and exchanged file, golden fixtures, and the zero-dependency C# package
  `UnityLudometry.Protocol` (with message types generated from the schemas) that the agent uses.
- `src/unity_ludometry_mcp/`: the start of the Python orchestrator: the protocol layer (models generated from the
  schemas, strict JSON, framing, envelopes, named-pipe/TCP transports), agent discovery and the agent client.
- [`docs/`](docs/README.md): documentation, including how to contribute.

The MCP server itself (`unity-ludometry-mcp`) follows. This README will then cover installation and how to register the
server with an MCP client.

## Building and testing
Requirements: Python 3.13 with [uv](https://docs.astral.sh/uv/), and the .NET SDK pinned in
`protocol/csharp/global.json` (10.0.x) for the C# protocol package.

```
uv sync --group dev
uv run pytest

cd protocol/csharp
dotnet build -c Release
dotnet test -c Release
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
