# tools

Developer scripts. Run them from the repository root with `uv run python tools/<script>`.

| Script | Does |
|---|---|
| `codegen.py [--check]` | Regenerates everything generated: the C# and Python protocol models (from `protocol/schema`) and the tool reference (`docs/tools.md`). With `--check`, fails if anything is out of date instead. |
| `tool_reference.py [--check]` | Regenerates only `docs/tools.md` from the server's tool definitions. |
