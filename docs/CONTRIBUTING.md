# Contributing to UnityLudometryMCP

Thanks for your interest! The project is pre-release. Today the repository contains the shared protocol; the Python
orchestrator is under construction, and this guide grows with it.

## Repository layout

| Path | What it is |
|---|---|
| `protocol/` | The schema-first protocol shared with the in-game agent. See [its README](../protocol/README.md). |
| `docs/` | Documentation. |

## Building and testing the protocol

Requirements: the .NET SDK pinned in `protocol/csharp/global.json` (10.0.x), and Python 3.10+ to regenerate the C#
message types after a schema change.

```
python protocol/codegen/csharp.py      # after changing schemas
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

CI also fails if the generated C# doesn't match the schemas (`python protocol/codegen/csharp.py --check`).

## Rules for the protocol package

- `UnityLudometry.Protocol` targets `netstandard2.0` and has **no dependencies**: it runs inside Unity games next to
  other mods, where any extra DLL could conflict. PolySharp adds modern C# syntax at compile time only.
- Everything on the wire is defined by a schema first, following the authoring rules in the protocol README. Add
  fixtures for every new case, including the relevant errors.
- Never edit `csharp/UnityLudometry.Protocol/Generated/`; regenerate it.
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
