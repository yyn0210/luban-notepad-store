# Contributing a plugin

Luban Notepad plugins are Lua packages. The store only distributes packages
that the existing plugin model can load: a zip containing `plugin.json` and Lua
sources. Native binaries, sidecars and platform-specific installers are not
supported.

## 1. Develop and release the plugin

1. Publish the plugin in its own public repository.
2. Build a release zip for version `X.Y.Z`. The archive must contain exactly one
   `plugin.json`; the manifest `id` and `version` must match the store entry.
3. Upload the zip to an immutable HTTPS URL. GitHub Releases are recommended:

   ```text
   https://github.com/<owner>/<repo>/releases/download/vX.Y.Z/<plugin-id>-X.Y.Z.zip
   ```

4. Record the SHA-256 and byte size of every uploaded package:

   ```bash
   sha256sum <plugin-id>-X.Y.Z.zip
   stat -c %s <plugin-id>-X.Y.Z.zip   # macOS: stat -f %z
   ```

## 2. Choose target platforms

A release may use one of these strategies:

- publish a single `universal` package that contains only Lua and resources and
  works on every platform;
- publish one package per target platform (for example `linux-x64` and
  `windows-x64`) when the plugin needs platform-specific Lua code or resources.

Targets:

```text
universal
linux-x64
linux-arm64
darwin-x64
darwin-arm64
windows-x64
windows-arm64
```

Each version must list at least one artifact. Partial coverage is allowed; the
editor only shows plugins that have an artifact for the current OS/CPU.

## 3. Add the entry

1. Copy `examples/plugin.example.json` to `plugins/<plugin-id>.json`.
2. Fill in the metadata, versions and artifacts. `latest_version` must equal
   the highest SemVer in `versions`.
3. Add a `localizations` entry if you can provide translated names or
   descriptions.
4. Run the checks:

   ```bash
   python3 scripts/build_catalog.py
   python3 scripts/validate.py
   ```

5. Commit both the source entry and the regenerated `catalog/index.json`.

## 4. Open a pull request

Describe:

- what the plugin does and which permissions it uses;
- whether it accesses the network or the filesystem;
- how each published target was built and tested;
- the source repository and release URL for every artifact;
- the license.

Reviewers check the manifest, permissions, package contents, artifact hashes
and target coverage. The `verified` flag is set by the store maintainers only;
do not set it yourself.

## Rules

- Artifact URLs must be HTTPS, immutable and free of credentials. Do not point
  an artifact at this catalog repository.
- `sha256` must be 64 hexadecimal characters and `size` must be exact.
- Do not publish a package whose `plugin.json` id or version differs from the
  entry.
- Do not use the store to distribute native executables or scripts that bypass
  the plugin sandbox.
- Keep a published version immutable. Publish a new version instead of replacing
  a released package.

CI runs `build_catalog.py --check` and `validate.py` for every pull request.
