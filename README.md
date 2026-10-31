# Luban Notepad Plugin Store

The plugin catalog for [Luban Notepad](https://github.com/yyn0210/luban-notepad).
Luban Notepad reads `catalog/index.json` from this repository and installs
plugin packages from the immutable HTTPS URLs listed in each entry.

Default catalog address used by the editor:

```text
https://raw.githubusercontent.com/yyn0210/luban-notepad-store/main/catalog/index.json
```

## Repository layout

```text
catalog/index.json              generated catalog read by the editor
plugins/<plugin-id>.json        authoritative plugin entries
examples/plugin.example.json    template, never published
schemas/plugin.schema.json      schema for one plugin entry
schemas/catalog.schema.json     schema for the generated catalog
scripts/build_catalog.py        regenerate catalog/index.json
scripts/validate.py             validate entries and consistency
.github/workflows/validate.yml  CI checks for every push and pull request
CONTRIBUTING.md                 publishing and review process
```

`plugins/` is the source of truth. `catalog/index.json` is generated; never edit
it by hand.

## How the editor uses the catalog

- The catalog is fetched in the background when the plugin store tab is opened,
  then cached under `<config-dir>/plugins/.store/`.
- Plugins are filtered by the current OS/CPU. An entry with an exact matching
  target artifact is preferred; otherwise a `universal` artifact is used.
- Plugins with no artifact for the current platform are not listed.
- Every download is checked against the catalog's SHA-256 and byte size before
  the existing plugin installer runs.
- Installed plugins keep the normal permission approval flow; the store cannot
  approve permissions on the user's behalf.

## Local checks

```bash
python3 scripts/build_catalog.py --check
python3 scripts/validate.py
```

To verify published artifacts as well (network access required, not used in
CI):

```bash
python3 scripts/validate.py --download
```

Only Python's standard library is required.

## Publishing

See [CONTRIBUTING.md](CONTRIBUTING.md). Version 1 does not sign artifacts or
run plugins automatically; entries and packages are reviewed through pull
requests.

## License

The catalog metadata in this repository is provided for use with Luban
Notepad. Plugin packages keep their own licenses as declared in each entry.
