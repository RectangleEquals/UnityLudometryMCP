# Configuration

## Environment variables

Set these in your MCP client's server entry (most clients accept an `env` object) or in the environment the client
starts from.

| Variable | Effect |
|---|---|
| `ULM_HOME` | Uses this folder as the profile root for this run instead of the default. It must be an absolute path. It isn't saved anywhere, so it applies only while it's set. |
| `ULM_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING` or `ERROR`. Logs go to stderr, which MCP clients usually show in their server log. |

## The profile root

The profile root is the one folder where the server keeps its own data. The default is the per-user local application
data folder: `%LOCALAPPDATA%\UnityLudometryMCP` on Windows. `server_status` shows the path in use and whether it
exists yet.

Machine settings (`settings.json` in the profile root) are added as the orchestrator grows. They never hold game data or
output paths.
