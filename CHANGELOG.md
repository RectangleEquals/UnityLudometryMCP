# Changelog

## 0.1.0-dev (unreleased)
- Shared protocol `0.1.0-dev.1` (versioned independently; see `protocol/README.md`): JSON Schemas for the envelope,
  the common types, all 171 agent methods, 22 event kinds and the exchanged files (discovery file, package manifest,
  NDJSON outputs); the zero-dependency C# package `UnityLudometry.Protocol` with message types and registries
  generated from the schemas (`protocol/codegen`).
- Protocol `0.1.0-dev.2`: the protocol version is named 0.1 (the wire format is unchanged). The schema reader is
  shared by the C# and the new Python generator.
- Protocol `0.1.0-dev.3`: the agent's diagnostics method is now `agent.healthCheck` (result types
  `AgentHealthCheckResult` and `HealthCheckItem`).
- Protocol `0.1.0-dev.4`: `content.export.start` exports textures (PNG), object data (JSON) and text assets (raw bytes);
  audio, meshes and fonts are left to static extraction (the `audio` and `mesh` formats are gone).
- Protocol `0.1.0-dev.5`: `ui.frameworks` (which UI frameworks the running game can use and uses, its input handling,
  and a classification per framework); `overlay.state` reports the overlay's `renderer`; the complete UI model: UI
  elements gain `interaction`, `visibility`, `visibleRect`, `scrollContainer`, `selected`, `navigation` and `rawText`,
  `ui.snapshot` pages with `cursor` and filters by `interaction` (as does `ui.find`), ui-marks carry `interaction` and
  `images`, and the new actions `ui.hover`, `ui.scrollTo` and `ui.navigate`.
- Facts `ui.frameworks_available`, `input.systems_present` and `ui.frameworks_used` (static usage merged with the agent's
  `ui.frameworks` reports: what the agent saw in use wins, with the screens it saw it on).
- Python project (`uv`, Python 3.13): the protocol layer (generated pydantic models, strict JSON, framing, envelopes,
  named-pipe/TCP transports), agent discovery, the agent client (handshake, requests, events, jobs, reconnect), the error
  model.
- The MCP server `unity-ludometry-mcp` (stdio, FastMCP) with `server_status`: versions, the profile root and the client's
  capabilities. `ULM_HOME` and `ULM_LOG_LEVEL`.
- The full package layout (placeholders for the parts still to come), `rules/` and `templates/` shipped in the wheel,
  ruff format, mypy, and a generated tool reference (`docs/tools.md`).
- User docs: getting started (install, register, what gets written where) and configuration.
- The MCP framework every tool builds on: the result envelope and error mapping; `@ulm_tool` (annotations, consent
  with `user_confirmed` or a direct question to the user when the client supports it, target/project resolution,
  background tasks); the task manager with `task_get`, `task_wait`, `task_cancel` and `task_list`; the event store with
  notices on the next result and `runtime_events`; the token budget (oversized results are cut down, the full result
  saved to a file, and every left-out part listed); the limit registry (`rules/limits.json`, precedence); tool groups
  with `tools_enable` / `tools_disable` (`ULM_TOOL_GROUPS=all` lists everything); the `ulm://status` and
  `ulm://guide/{topic}` resources; the daily server log in the profile root and warnings mirrored to the client.
- The profile store: machine settings (`config_get` / `config_set`, with release pins for the agent, the dnSpy bridge
  and BepInEx 5 x64/x86); targets and projects with provenance-ranked facts (`target_list`, `target_info`,
  `target_set_fact`, `target_remove`, `project_open`, `project_list`, `project_info`, `project_set_fact`,
  `project_close`, `project_remove`); derived manifests; ledgers of every file ULM writes or installs outside the
  profile; user-chosen output paths, validated and never inside the game (`paths_get`, `paths_set`, `exports_list`,
  `exports_clean`). Removing a target or project is refused while ULM still has files installed or deployed in the
  game. Results now say which target and project they used. New error code `INVALID_ARGUMENT`.
