# Protocol

The wire protocol between the UnityLudometryMCP orchestrator and the in-game UnityRuntimeAnalysisAgent (and, later,
other providers such as a static-analysis bridge). It is **schema-first**: the JSON Schemas in `schema/` are the
normative definition, and the code in `csharp/` (and the orchestrator's Python models) is generated from them.

**Current version: 0.1** (pre-release, tag `protocol-v0.1.0-dev.9`). It covers the agent's complete v0.1 surface:
188 methods, 23 event kinds and the files the agent writes.

## Layout

| Path | Contents |
|---|---|
| `schema/envelope.schema.json` | The envelope every frame carries: request, response (result or error) or event |
| `schema/common/` | Shared types: error, warning, anchor, handle descriptor, target, member path, view, encoded value, redaction stub, locator, jobs, paging, observations, conditions, output files, captures, rules, probes, tests, log entries, instrumentation records, … |
| `schema/methods/<method>.schema.json` | One file per method: `$defs/params`, `$defs/result`, `$defs/jobResult` (job methods), and execution metadata in `x-method` (`thread`, `minMode`, `job`, `mutating`, `requires`) |
| `schema/events/<kind>.schema.json` | One file per event kind, with `$defs/params` |
| `schema/files/` | Exchanged files: the discovery file, the release `package.json`, and the NDJSON outputs (`ndjson` header/footer plus survey, IL index, content scan, trace, export manifest, metrics records) |
| `schema/bridge/` | Methods and events of static-analysis bridges (added later) |
| `codegen/` | Generators for the C# message types and the Python models (sharing one schema reader) |
| `csharp/` | `UnityLudometry.Protocol` (netstandard2.0, zero dependencies) |

## Transport and framing

- One connection per client over a local named pipe (TCP on loopback as a fallback). Each frame is a 4-byte
  little-endian payload length followed by a UTF-8 JSON payload. The default maximum payload is 16 MiB.
- The first request on a connection must be `hello` with the session token from the agent's discovery file.
- Responses may arrive out of order and are matched by `id`. Events carry a per-connection `seq`; a gap means event
  batches were dropped under back-pressure (responses are never dropped).
- `context` on a request is echoed unchanged on its response and on every event the request produces.
- Long-running methods (`x-method.job`) return `{jobId, kind}`; their result (`$defs/jobResult`) arrives through
  `job.get` / `job.wait` or the `job.finished` event.

## Versioning

- The protocol has its own `major.minor` version, independent of the orchestrator and agent releases. It changes only
  when the wire format does. Tags: `protocol-vX.Y.Z` (development tags `protocol-vX.Y.Z-dev.N`).
- The envelope's `v` is the major version.
- **Before 1.0 (now):** the protocol is pre-release. Both sides must speak exactly the same `major.minor`; otherwise the
  agent answers `hello` with `PROTOCOL_MISMATCH`.
- **From 1.0:** minor versions only add optional fields, methods and event kinds; a major change is breaking.
- Readers ignore unknown properties (the C# message types keep them, so they survive a round-trip), and treat unknown
  error codes as generic failures.

## Schema authoring rules

These keep the schemas and the generated code consistent; the generator enforces them.
- JSON Schema draft 2020-12. `$id` = `https://github.com/RectangleEquals/UnityLudometryMCP/protocol/schema/<path>`,
  and `$ref`s are relative.
- Every object with `properties` has a `title`: its (unique, PascalCase) type name in generated code.
- A property that may be `null` is **required**. Canonical form: such properties are always written; absent optional
  properties are omitted. `{"anyOf": [X, {"type": "null"}]}` is a nullable X.
- Other unions, untyped values and fixed-length arrays become raw JSON values in generated code.
- Descriptions are self-contained.

## Generated Python models

`python protocol/codegen/python.py` regenerates `src/unity_ludometry_mcp/protocol/generated/`: one pydantic model per
titled object (strict validation, snake_case fields with the JSON names as aliases, unknown properties kept, canonical
`to_json()`), plus `METHODS`, `EVENTS` and `FILES`. Integer fields accept integral numbers in the 64-bit range (e.g.
`5.0`), the same rule as the C# package. `--check` fails if the models don't match the schemas.

## Generated C# types

`python protocol/codegen/csharp.py` (Python 3.10+, standard library only) regenerates
`csharp/UnityLudometry.Protocol/Generated/`: one class per titled object (with `Read` / `WriteJson`), the `Methods` and
`EventKinds` name constants, and the `MethodRegistry` (metadata + message types per method), `EventRegistry` and
`FileRegistry`. Never edit the generated files; `--check` fails if they don't match the schemas.

## Changing the protocol

The protocol is changed only in this repository.
1. Change or add the schemas (following the authoring rules).
2. Regenerate the C# types and the Python models (`python protocol/codegen/csharp.py`, `python protocol/codegen/python.py`).
3. Tag a new version. Consumers then bump their protocol submodule.

## Using the C# package from another repository

Add this repository as a git submodule (e.g. `external/protocol`), and reference
`protocol/csharp/UnityLudometry.Protocol/UnityLudometry.Protocol.csproj`. The `csharp/` folder
carries its own build settings, so it builds identically inside the consuming solution. `MethodRegistry` gives each
method's thread, minimum mode, job and mutating flags, which an implementation can use for dispatch and
`agent.capabilities`.
