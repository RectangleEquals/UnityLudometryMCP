# Configuration

## Environment variables

Set these in your MCP client's server entry (most clients accept an `env` object) or in the environment the client
starts from.

| Variable | Effect |
|---|---|
| `ULM_HOME` | Uses this folder as the profile root for this run instead of the default. It must be an absolute path. It isn't saved anywhere, so it applies only while it's set. |
| `ULM_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING` or `ERROR`. Logs go to stderr (MCP clients usually show it in their server log) and to the server log in the profile root. |
| `ULM_TOOL_GROUPS` | `all` lists every tool from the start. By default (`dynamic`) only some tool groups are listed, to save your assistant's context, and `tools_enable` lists more. Use `all` if your client doesn't refresh its tool list when told to. (Clients on the 2026-07-28 MCP protocol, which can't be told, get every tool automatically.) |

## The profile root

The profile root is the one folder where the server keeps its own data. The default is the per-user local application
data folder: `%LOCALAPPDATA%\UnityLudometryMCP` on Windows. `server_status` shows the path in use and whether it
exists yet.

The server writes its log to `logs\ulm-<date>.log` in the profile root (the last 14 days are kept). Results too large
to return in one piece are saved to `logs\results\` (or, once a game or project is open, next to its data) and
referenced from the result.

Machine settings (`settings.json` in the profile root) are added as the orchestrator grows. They never hold game data or
output paths.

## Limits

Limits keep the work the server does, and the size of what it returns, in check: for example `response.max_tokens`
(6000 by default), the size of one tool result. The shipped defaults and their hard maximums are in
[`rules/limits.json`](../rules/limits.json). Changing them comes with a later version.
