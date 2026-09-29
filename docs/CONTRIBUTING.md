# Contributing to UnityLudometryMCP

Thanks for your interest! The project is pre-release. Today the repository contains the shared protocol, the Python
orchestrator's protocol layer and agent client, and a minimal MCP server; this guide grows with it.

## Repository layout

| Path | What it is |
|---|---|
| `protocol/` | The schema-first protocol shared with the in-game agent. See [its README](../protocol/README.md). |
| `src/unity_ludometry_mcp/` | The Python orchestrator. `server.py` creates the MCP server; `tools/` has one module per tool group (each registers its tools with `register(app)`); `protocol/` is the protocol layer (generated models in `protocol/generated/`); `providers/` has discovery and the agent client. The other packages (`profiles/`, `data/`, `pipeline/`, `advisor/`, `runtime/`, …) are placeholders that fill in as features land. |
| `rules/` | Shipped defaults (fingerprinting markers, limits, release pins, guides, …), packaged into the wheel. |
| `templates/` | `dotnet new` templates for mods, tests, live patches and snippets, packaged into the wheel. |
| `tools/` | Developer scripts: `codegen.py` regenerates everything generated. See [its README](../tools/README.md). |
| `docs/` | Documentation. `tools.md` is generated. |

## Building the Python orchestrator

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/).

```
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run mypy
uv run python tools/codegen.py --check
```

- `uv.lock` pins every dependency (`uv sync --locked` installs exactly those).
- `ruff format` formats the code (generated code excepted). `mypy` is strict for `profiles`, `data`, `pipeline`,
  `advisor`, `limits`, `consent` and `protocol`.
- Tool names, descriptions, annotations and parameters are what the LLM sees: after a wording change, check that the
  new text still tells the LLM the right thing.
- A new tool is an async function declared with `@ulm_tool` (in `tools/__init__.py`) in its group's module, added to
  that module's `register(app)`:

  ```python
  @ulm_tool(group="runtime", title="Read a value", read_only=True, idempotent=True, scope="target")
  async def live_value(call: ToolCall, locator: Annotated[str, Field(description="...")]) -> Result:
      """What the tool does, written for the LLM that calls it."""
      ...
  ```

  The decorator adds the MCP annotations (`openWorldHint` is always false), the `target`/`project` parameters and
  their resolution (`scope`), the `user_confirmed` parameter and the consent flow (`needs_confirmation`), background
  tasks (`long_running`), notices, the token budget, and error mapping: raise `UlmError` for expected failures.
  Return data or a `Result` (`envelope.py`). Then regenerate the tool reference (`uv run python tools/codegen.py`).
- The limits (`rules/limits.json`) are read through `call.limit(key)`, which applies the precedence rules.
- Tools that only touch the profile store's small files can be plain `def` functions; tools that wait on providers or
  run tasks are `async`.
- The profile store (`profiles/`) never hardcodes a machine path: folders come from `platformdirs`, `ULM_HOME` or the
  user. Every file written outside the profile is recorded in a ledger (`profiles/ledgers.py`).
- Never print to stdout in the server: over stdio, stdout carries the MCP messages. Log through `logging` (stderr).

## Building the protocol

Requirements: the .NET SDK pinned in `protocol/csharp/global.json` (10.0.x), and Python 3.10+ to regenerate the C#
message types after a schema change.

```
python protocol/codegen/csharp.py      # after changing schemas
python protocol/codegen/python.py
cd protocol/csharp
dotnet build -c Release
```

Warnings are errors. `python protocol/codegen/csharp.py --check` and `python protocol/codegen/python.py --check` fail if
the generated C# or Python doesn't match the schemas.

## Rules for the protocol package

- `UnityLudometry.Protocol` targets `netstandard2.0` and has **no dependencies**: it runs inside Unity games next to
  other mods, where any extra DLL could conflict. PolySharp adds modern C# syntax at compile time only.
- Everything on the wire is defined by a schema first, following the authoring rules in the protocol README.
- Never edit `csharp/UnityLudometry.Protocol/Generated/` or `src/unity_ludometry_mcp/protocol/generated/`; regenerate them.
- Schema descriptions and code comments must stand on their own. Explain the reason where it's needed.
- Follow the versioning rules in the protocol README. Before 1.0, any wire change needs a new protocol version.

## Code style

`.editorconfig` is the reference: 4-space indentation (2 for JSON/YAML/project files), file-scoped namespaces,
`_camelCase` private fields, nullable reference types enabled. Public members of the protocol package need XML
documentation.

## Pull requests

- Keep each pull request focused, and check that it builds and works before opening it.
- Update the docs your change affects (the READMEs, this guide, `CHANGELOG.md`).
- Don't commit personal information or machine-specific paths: no user names, absolute paths, local settings files or
  game files.

By contributing, you agree that your contributions are licensed under the [MIT License](../LICENSE).
