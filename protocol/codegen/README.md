# codegen

Generators that turn the schemas in `../schema` into code. Generated code is committed, and CI regenerates it and fails
if it differs from the committed files. Both generators read the schemas through `schema_ir.py`, so C# and Python
interpret them identically.

| File | Purpose | Run |
|---|---|---|
| `schema_ir.py` | Reads the schemas into a language-neutral model and enforces the authoring rules | (imported by the generators) |
| `csharp.py` | `../csharp/UnityLudometry.Protocol/Generated/`: message types, `Methods` / `EventKinds` constants, `MethodRegistry`, `EventRegistry`, `FileRegistry` | `python protocol/codegen/csharp.py` (`--check` verifies the committed output) |
| `python.py` | `../../src/unity_ludometry_mcp/protocol/generated/`: pydantic models, `Methods` / `EventKinds` / `ErrorCodes`, `METHODS`, `EVENTS`, `FILES` | `python protocol/codegen/python.py` (`--check` verifies the committed output) |

The generators need Python 3.10+ and only the standard library; the generated Python models need pydantic 2.11+.
All of them follow the schema authoring rules in the [protocol README](../README.md#schema-authoring-rules).
