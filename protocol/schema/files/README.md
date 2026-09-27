# files

Record schemas for the bulk NDJSON files the agent writes (surveys, IL indexes, content scans, traces, export manifests,
metrics). Every file starts with a `header` record and ends with a `footer` record carrying record counts and the SHA-256
of all preceding lines.

Not added yet: each schema arrives with the feature that produces the file.
