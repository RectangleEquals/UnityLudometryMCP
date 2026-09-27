# Changelog

## 0.1.0-dev (unreleased)
- Shared protocol `0.1.0-dev.1` (versioned independently; see `protocol/README.md`): JSON Schemas for the envelope,
  the common types, all 171 agent methods, 22 event kinds and the exchanged files (discovery file, package manifest,
  NDJSON outputs); golden fixtures for every method, event and file; the zero-dependency C# package
  `UnityLudometry.Protocol` with message types and registries generated from the schemas (`protocol/codegen`), the
  `UnityLudometry.Protocol.Conformance` library, and tests.
