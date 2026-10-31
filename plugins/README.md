# Plugin entries

Each file in this directory is one published plugin and is the authoritative
source for the generated catalog.

- File name: `<plugin-id>.json`, for example `com.example.hello.json`.
- Content: one complete plugin object as described by
  [`schemas/plugin.schema.json`](../schemas/plugin.schema.json).
- `latest_version` must equal the highest SemVer in `versions`.
- Every version must list at least one artifact. A version may support
  `universal` or only a subset of the six target platforms.
- Artifact URLs must be immutable HTTPS URLs (GitHub Releases are recommended).
- Build the catalog with `python3 scripts/build_catalog.py` and validate with
  `python3 scripts/validate.py`.

Start from [`examples/plugin.example.json`](../examples/plugin.example.json).
Do not place the example file directly in this directory.
