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
| `tests/` | `unit/`, `protocol/` (models vs fixtures, codec, framing), `integration/` (the server through an MCP client, the fake agent), `contract/` (what the LLM sees of every tool), `dotnet/` (C# builds), `fakes/` (a fake agent that speaks the real protocol) and `fixtures/`. |
| `tools/` | Developer scripts: `codegen.py` regenerates everything generated. See [its README](../tools/README.md). |
| `docs/` | Documentation. `tools.md` is generated. |

## Building and testing the Python orchestrator

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/).

```
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
uv run pytest -m dotnet          # needs the .NET SDK
uv run python tools/codegen.py --check
```

- `uv.lock` pins every dependency; CI installs with `uv sync --locked`.
- `ruff format` formats the code (generated code excepted). `mypy` is strict for `profiles`, `data`, `pipeline`,
  `advisor`, `limits`, `consent` and `protocol`.
- Test markers: `windows` (real named pipes; CI runs on Windows), `slow`, `dotnet` (builds C#; excluded from the default
  run, run with `-m dotnet`), and `integration_real` (a real game and agent; excluded by default, and skipped unless
  `ULM_TEST_SETTINGS` names a local settings file kept outside the repository).
- `tests/contract/` snapshots every tool's name, description, annotations and parameters. A wording change fails the
  test on purpose: check that the new text still tells the LLM the right thing, then run
  `uv run pytest tests/contract --snapshot-update`.
- A new tool: add it to its group module's `register(app)`, then regenerate the tool reference
  (`uv run python tools/codegen.py`). Every tool declares all four MCP annotations, and `openWorldHint` is false.
- Never print to stdout in the server: over stdio, stdout carries the MCP messages. Log through `logging` (stderr).
- `tests/fakes/agent.py` is a fake agent that speaks the real protocol, answers from the golden fixtures and validates
  every request against the schemas. Use it for anything that talks to the agent.

## Building and testing the protocol

Requirements: the .NET SDK pinned in `protocol/csharp/global.json` (10.0.x), and Python 3.10+ to regenerate the C#
message types after a schema change.

```
python protocol/codegen/csharp.py      # after changing schemas
python protocol/codegen/python.py
cd protocol/csharp
dotnet build -c Release
dotnet test -c Release
```

Warnings are errors. The tests check:
- the JSON reader, writer and framing (including malformed input, limits and a 16 MiB frame);
- that every schema is valid JSON Schema draft 2020-12 with the right `$id`, and that every `$ref` resolves;
- that every fixture validates against the schemas and round-trips through the generated types (file fixtures too,
  including NDJSON footer hashes and counts);
- that schemas, fixtures, registries, constants and error codes cover each other, and that the package has no
  dependencies.

CI also fails if the generated C# or Python doesn't match the schemas (`python protocol/codegen/csharp.py --check`,
`python protocol/codegen/python.py --check`).

## Rules for the protocol package

- `UnityLudometry.Protocol` targets `netstandard2.0` and has **no dependencies**: it runs inside Unity games next to
  other mods, where any extra DLL could conflict. PolySharp adds modern C# syntax at compile time only.
- Everything on the wire is defined by a schema first, following the authoring rules in the protocol README. Add
  fixtures for every new case, including the relevant errors.
- Never edit `csharp/UnityLudometry.Protocol/Generated/` or `src/unity_ludometry_mcp/protocol/generated/`; regenerate them.
- Schema descriptions and code comments must stand on their own. Explain the reason where it's needed.
- Follow the versioning rules in the protocol README. Before 1.0, any wire change needs a new protocol version.

## Code style

`.editorconfig` is the reference: 4-space indentation (2 for JSON/YAML/project files), file-scoped namespaces,
`_camelCase` private fields, nullable reference types enabled. Public members of the protocol package need XML
documentation.

## Pull requests

- Keep each pull request focused, with tests for new behaviour. CI (Windows) must be green.
- Update the docs your change affects (the READMEs, this guide, `CHANGELOG.md`).
- Don't commit personal information or machine-specific paths: no user names, absolute paths, local settings files or
  game files. CI rejects known personal terms.

By contributing, you agree that your contributions are licensed under the [MIT License](../LICENSE).
