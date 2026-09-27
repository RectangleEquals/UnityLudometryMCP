# codegen

Generators that turn the schemas in `../schema` into code. Generated code is committed, and CI regenerates it and fails
if it differs from the committed files.

| Generator | Output | Run |
|---|---|---|
| `csharp.py` (Python 3.10+, standard library only) | `../csharp/UnityLudometry.Protocol/Generated/`: message types, `Methods` / `EventKinds` constants, `MethodRegistry`, `EventRegistry`, `FileRegistry` | `python protocol/codegen/csharp.py` (`--check` verifies the committed output) |

The generator for the orchestrator's Python models arrives together with the Python orchestrator.

Both follow the schema authoring rules in the [protocol README](../README.md#schema-authoring-rules).
