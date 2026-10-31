#!/usr/bin/env python3
"""Generate catalog/index.json from plugins/*.json.

The plugins directory is the authoritative source. Each file is one complete
plugin object. The catalog keeps plugins sorted by id so regenerating it is
deterministic.

Usage:
    python3 scripts/build_catalog.py          # write catalog/index.json
    python3 scripts/build_catalog.py --check  # fail when the file is stale

No third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
CATALOG_PATH = ROOT / "catalog" / "index.json"

DEFAULT_GENERATED_AT = "2026-10-31T00:00:00Z"
REPOSITORY = {
    "id": "luban-notepad-official",
    "name": "Luban Notepad Plugin Store",
    "homepage": "https://github.com/yyn0210/luban-notepad-store",
}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def plugin_files() -> list[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(
        path
        for path in PLUGINS_DIR.glob("*.json")
        if path.is_file() and not path.name.startswith(".")
    )


def collect_plugins(errors: list[str]) -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in plugin_files():
        try:
            value = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {error}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.relative_to(ROOT)}: plugin entry must be an object")
            continue
        plugin_id = value.get("id")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            errors.append(f"{path.relative_to(ROOT)}: id is required")
            continue
        if path.stem != plugin_id:
            errors.append(
                f"{path.relative_to(ROOT)}: file name must be '{plugin_id}.json'"
            )
            continue
        if plugin_id in seen:
            errors.append(f"{path.relative_to(ROOT)}: duplicate plugin id '{plugin_id}'")
            continue
        seen.add(plugin_id)
        plugins.append(value)
    plugins.sort(key=lambda plugin: plugin["id"])
    return plugins


def current_repository() -> dict[str, Any]:
    if CATALOG_PATH.is_file():
        try:
            existing = read_json(CATALOG_PATH)
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict):
            repository = existing.get("repository")
            if (
                isinstance(repository, dict)
                and isinstance(repository.get("id"), str)
                and isinstance(repository.get("name"), str)
            ):
                return repository
    return dict(REPOSITORY)


def generated_at(plugins: list[dict[str, Any]]) -> str:
    existing = None
    if CATALOG_PATH.is_file():
        try:
            existing = read_json(CATALOG_PATH)
        except (OSError, json.JSONDecodeError):
            existing = None
    if (
        isinstance(existing, dict)
        and existing.get("plugins") == plugins
        and isinstance(existing.get("generated_at"), str)
    ):
        return existing["generated_at"]

    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch and source_date_epoch.isdigit():
        moment = datetime.fromtimestamp(int(source_date_epoch), timezone.utc)
    else:
        moment = datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_catalog(plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "$schema": "../schemas/catalog.schema.json",
        "catalog_version": 1,
        "repository": current_repository(),
        "generated_at": generated_at(plugins),
        "plugins": plugins,
    }


def render(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify catalog/index.json matches plugins/ instead of writing it",
    )
    args = parser.parse_args()

    errors: list[str] = []
    plugins = collect_plugins(errors)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    catalog = build_catalog(plugins)
    rendered = render(catalog)

    if args.check:
        if not CATALOG_PATH.is_file():
            print(
                f"{CATALOG_PATH.relative_to(ROOT)} is missing; "
                "run python3 scripts/build_catalog.py",
                file=sys.stderr,
            )
            return 1
        existing = CATALOG_PATH.read_text(encoding="utf-8")
        if existing != rendered:
            print(
                "catalog/index.json is out of date; run "
                "python3 scripts/build_catalog.py and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"catalog is up to date ({len(plugins)} plugin(s))")
        return 0

    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {CATALOG_PATH.relative_to(ROOT)} ({len(plugins)} plugin(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
