# Changelog

## 0.1.0-dev (unreleased)
- Shared protocol `0.1.0-dev.1` (versioned independently; see `protocol/README.md`): JSON Schemas for the envelope,
  the common types, all 171 agent methods, 22 event kinds and the exchanged files (discovery file, package manifest,
  NDJSON outputs); golden fixtures for every method, event and file; the zero-dependency C# package
  `UnityLudometry.Protocol` with message types and registries generated from the schemas (`protocol/codegen`), the
  `UnityLudometry.Protocol.Conformance` library, and tests.
- Protocol `0.1.0-dev.2`: fixtures that named the protocol version now name 0.1 (the wire format is unchanged); tests on
  both sides check it. The schema reader is shared by the C# and the new Python generator.
- Python project (`uv`, Python 3.13): the protocol layer (generated pydantic models, strict JSON, framing, envelopes,
  named-pipe/TCP transports), agent discovery, the agent client (handshake, requests, events, jobs, reconnect), the error
  model, and a fake agent for tests.
- The MCP server `unity-ludometry-mcp` (stdio, FastMCP) with `server_status`: versions, the profile root and the client's
  capabilities. `ULM_HOME` and `ULM_LOG_LEVEL`.
- The full package layout (placeholders for the parts still to come), `rules/` and `templates/` shipped in the wheel,
  ruff format, mypy, tool contract snapshots, a generated tool reference (`docs/tools.md`), and CI for all of it.
- User docs: getting started (install, register, what gets written where) and configuration.
