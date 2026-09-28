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

## Machine settings

`settings.json` in the profile root holds what belongs to this machine: where tools are installed (`dotnet_path`,
`dnspy_path`, `assetstudio_cli_path`), the pinned releases ULM may download and install (the in-game agent, the dnSpy
bridge, and BepInEx 5 for 64-bit and 32-bit games, each with its SHA-256), machine-wide limit defaults (`limits.*`),
defaults for the in-game overlay (`ui.*`), and `log_level`. Your assistant reads and changes them with `config_get` and
`config_set`. They never hold game data or output folders.

The file is created the first time a setting changes; until then the shipped defaults apply. The .NET SDK is found on
`PATH` automatically; `dotnet_path` is only needed if it isn't there.

## Games, projects and output folders

Each game you work on (a *target*) gets a folder under `targets\` in the profile root with what ULM learned about it
(*facts*, each recording where it came from), its knowledge and its logs. A *project* is a piece of work on that game,
usually a mod, with its own folder inside the target's.

ULM writes outside the profile root only to folders you choose, and never inside the game's install folder. Those
folders are *output paths*, set per game or per project (`paths_set`): where exported assets, decompiled code, the mod's
source project and exported mods go. ULM never picks one for you; when it needs one, it asks. Every file it writes there
is recorded, so it can later be listed (`exports_list`), moved with the folder, or deleted (`exports_clean`, which only
deletes files that are unchanged since ULM wrote them).

## Limits

Limits keep the work the server does, and the size of what it returns, in check: for example `response.max_tokens`
(6000 by default), the size of one tool result. The shipped defaults and their hard maximums are in
[`rules/limits.json`](../rules/limits.json). Changing them comes with a later version.
