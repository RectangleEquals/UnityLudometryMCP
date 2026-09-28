# Test fixtures

Synthetic inputs for the tests. Nothing here comes from a real game.

| Folder | Holds |
|---|---|
| `fake_installs/` | Directory trees that imitate Unity game installs (Mono and IL2CPP, content layouts, loaders, middleware markers) |
| `ndjson/` | Agent output samples (surveys, IL index, content scans, traces) generated from the agent's own fixture game |
| `assetstudio/` | Asset lists and MonoBehaviour exports from the fixture game's bundles |
| `advisor/` | Labelled questions for the capability advisor, with the expected decisions |

The folders are added with the features that use them. The protocol's golden fixtures live in `protocol/fixtures/`.
