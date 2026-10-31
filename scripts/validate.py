#!/usr/bin/env python3
"""Validate the Luban Notepad plugin store.

Checks catalog/index.json, plugins/*.json, the example entry, and that the
catalog matches the plugin sources. No third-party dependencies.

Usage:
    python3 scripts/validate.py
    python3 scripts/validate.py --download   # also download and hash artifacts

Network access is off by default; CI never enables --download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "catalog" / "index.json"
PLUGINS_DIR = ROOT / "plugins"
EXAMPLES_DIR = ROOT / "examples"

MAX_CATALOG_BYTES = 8 * 1024 * 1024
MAX_PLUGIN_ENTRY_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024

TARGETS = {
    "universal",
    "linux-x64",
    "linux-arm64",
    "darwin-x64",
    "darwin-arm64",
    "windows-x64",
    "windows-arm64",
}

PLUGIN_FIELDS = {
    "$schema",
    "id",
    "name",
    "description",
    "publisher",
    "verified",
    "icon",
    "tags",
    "permissions",
    "source",
    "homepage",
    "license",
    "latest_version",
    "versions",
    "localizations",
}
VERSION_FIELDS = {
    "version",
    "api_version",
    "released_at",
    "release_notes",
    "artifacts",
}
ARTIFACT_FIELDS = {"target", "url", "sha256", "size"}
LOCALIZATION_FIELDS = {"name", "description"}
CATALOG_FIELDS = {
    "$schema",
    "catalog_version",
    "repository",
    "generated_at",
    "plugins",
}
REPOSITORY_FIELDS = {"id", "name", "homepage"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def error(errors: list[str], path: Path, location: str, reason: str) -> None:
    try:
        name = path.relative_to(ROOT)
    except ValueError:
        name = path
    errors.append(f"{name}: {location}: {reason}")


def read_bytes(path: Path, errors: list[str], limit: int) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        error(errors, path, "$", f"cannot read file: {exc}")
        return None
    if len(data) > limit:
        error(errors, path, "$", f"file is larger than {limit} bytes")
        return None
    return data


def parse_json(path: Path, errors: list[str], limit: int = MAX_PLUGIN_ENTRY_BYTES) -> Any:
    data = read_bytes(path, errors, limit)
    if data is None:
        return None
    try:
        text = data.decode("utf-8-sig")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        error(errors, path, "$", f"invalid JSON: {exc}")
        return None


def is_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(ch.isspace() for ch in value) or "\\" in value or "#" in value:
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.fragment
    )


def is_catalog_repository_url(value: str) -> bool:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    path = parts.path.lower()
    return host in {"github.com", "raw.githubusercontent.com"} and (
        "luban-notepad-store" in path
    )


def semver_parts(value: str) -> tuple[int, int, int, list[str] | None] | None:
    match = SEMVER_RE.match(value)
    if not match:
        return None
    prerelease = match.group(4)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        prerelease.split(".") if prerelease is not None else None,
    )


def compare_prerelease(left: list[str] | None, right: list[str] | None) -> int:
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1
    for left_item, right_item in zip(left, right):
        if left_item == right_item:
            continue
        left_number = left_item.isdigit()
        right_number = right_item.isdigit()
        if left_number and right_number:
            return -1 if int(left_item) < int(right_item) else 1
        if left_number:
            return -1
        if right_number:
            return 1
        return -1 if left_item < right_item else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def compare_semver(left: str, right: str) -> int:
    left_parts = semver_parts(left)
    right_parts = semver_parts(right)
    if left_parts is None or right_parts is None:
        raise ValueError("invalid SemVer")
    for index in range(3):
        if left_parts[index] != right_parts[index]:
            return -1 if left_parts[index] < right_parts[index] else 1
    return compare_prerelease(left_parts[3], right_parts[3])


def check_string(
    value: Any,
    errors: list[str],
    path: Path,
    location: str,
    label: str,
    minimum: int = 1,
    maximum: int = 128,
) -> None:
    if not isinstance(value, str):
        error(errors, path, location, f"{label} is required and must be a string")
        return
    if len(value) < minimum or len(value) > maximum:
        error(
            errors,
            path,
            location,
            f"{label} must be {minimum}-{maximum} characters",
        )


def check_https_url(
    value: Any, errors: list[str], path: Path, location: str, label: str
) -> None:
    if not is_https_url(value):
        error(
            errors,
            path,
            location,
            f"{label} must be an absolute HTTPS URL without credentials or fragment",
        )


def check_string_array(
    value: Any,
    errors: list[str],
    path: Path,
    location: str,
    label: str,
    maximum: int = 64,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        error(errors, path, location, f"{label} must be an array")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(item, str):
            error(errors, path, item_location, f"{label} entries must be strings")
            continue
        if not item or len(item) > maximum:
            error(
                errors,
                path,
                item_location,
                f"{label} entries must be 1-{maximum} characters",
            )
        if item in seen:
            error(errors, path, item_location, f"duplicate {label} entry '{item}'")
        seen.add(item)


def validate_localizations(value: Any, errors: list[str], path: Path, location: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        error(errors, path, location, "localizations must be an object")
        return
    for tag, entry in value.items():
        entry_location = f"{location}.{tag}"
        if not tag or len(tag) > 35:
            error(errors, path, entry_location, "language tag must be 1-35 characters")
        if not isinstance(entry, dict):
            error(errors, path, entry_location, "localization must be an object")
            continue
        unknown = sorted(set(entry) - LOCALIZATION_FIELDS)
        if unknown:
            error(errors, path, entry_location, f"unknown fields: {', '.join(unknown)}")
        check_string(entry.get("name"), errors, path, f"{entry_location}.name", "name")
        if "description" in entry and not isinstance(entry["description"], str):
            error(errors, path, f"{entry_location}.description", "description must be a string")


def validate_artifact(value: Any, errors: list[str], path: Path, location: str) -> None:
    if not isinstance(value, dict):
        error(errors, path, location, "artifact must be an object")
        return
    unknown = sorted(set(value) - ARTIFACT_FIELDS)
    if unknown:
        error(errors, path, location, f"unknown fields: {', '.join(unknown)}")
    target = value.get("target")
    if not isinstance(target, str) or target not in TARGETS:
        error(
            errors,
            path,
            f"{location}.target",
            f"target must be one of: {', '.join(sorted(TARGETS))}",
        )
    check_https_url(value.get("url"), errors, path, f"{location}.url", "url")
    url = value.get("url")
    if is_https_url(url) and is_catalog_repository_url(url):
        error(
            errors,
            path,
            f"{location}.url",
            "artifact url must not point at the catalog repository",
        )
    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or not SHA256_RE.match(sha256):
        error(
            errors,
            path,
            f"{location}.sha256",
            "sha256 must be 64 hexadecimal characters",
        )
    size = value.get("size")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 1
        or size > MAX_ARTIFACT_BYTES
    ):
        error(
            errors,
            path,
            f"{location}.size",
            f"size must be an integer between 1 and {MAX_ARTIFACT_BYTES}",
        )


def validate_version(value: Any, errors: list[str], path: Path, location: str) -> None:
    if not isinstance(value, dict):
        error(errors, path, location, "version entry must be an object")
        return
    unknown = sorted(set(value) - VERSION_FIELDS)
    if unknown:
        error(errors, path, location, f"unknown fields: {', '.join(unknown)}")
    version = value.get("version")
    if not isinstance(version, str) or semver_parts(version) is None:
        error(errors, path, f"{location}.version", "version must be valid SemVer")
    api_version = value.get("api_version", 1)
    if (
        not isinstance(api_version, int)
        or isinstance(api_version, bool)
        or api_version < 1
    ):
        error(
            errors,
            path,
            f"{location}.api_version",
            "api_version must be a positive integer",
        )
    for key in ("released_at", "release_notes"):
        if key in value and not isinstance(value[key], str):
            error(errors, path, f"{location}.{key}", f"{key} must be a string")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        error(errors, path, f"{location}.artifacts", "artifacts is required and must be an array")
        return
    if not artifacts:
        error(errors, path, f"{location}.artifacts", "artifacts must not be empty")
        return
    targets: set[str] = set()
    for index, artifact in enumerate(artifacts):
        artifact_location = f"{location}.artifacts[{index}]"
        validate_artifact(artifact, errors, path, artifact_location)
        if isinstance(artifact, dict):
            target = artifact.get("target")
            if isinstance(target, str):
                if target in targets:
                    error(
                        errors,
                        path,
                        f"{artifact_location}.target",
                        f"duplicate target '{target}'",
                    )
                targets.add(target)


def validate_plugin(value: Any, errors: list[str], path: Path) -> None:
    location = "$"
    if not isinstance(value, dict):
        error(errors, path, location, "plugin entry must be an object")
        return
    unknown = sorted(set(value) - PLUGIN_FIELDS)
    if unknown:
        error(errors, path, location, f"unknown fields: {', '.join(unknown)}")

    plugin_id = value.get("id")
    if not isinstance(plugin_id, str) or not ID_RE.match(plugin_id) or len(plugin_id) > 128:
        error(
            errors,
            path,
            "$.id",
            "id must match [a-z0-9][a-z0-9._-]* and be at most 128 characters",
        )
    check_string(value.get("name"), errors, path, "$.name", "name")
    check_string(value.get("publisher"), errors, path, "$.publisher", "publisher")
    if "description" in value and not isinstance(value["description"], str):
        error(errors, path, "$.description", "description must be a string")
    if "verified" in value and not isinstance(value["verified"], bool):
        error(errors, path, "$.verified", "verified must be a boolean")
    if "icon" in value:
        check_https_url(value["icon"], errors, path, "$.icon", "icon")
    check_string_array(value.get("tags"), errors, path, "$.tags", "tags")
    check_string_array(value.get("permissions"), errors, path, "$.permissions", "permissions")
    if "source" in value:
        check_https_url(value["source"], errors, path, "$.source", "source")
    if "homepage" in value:
        check_https_url(value["homepage"], errors, path, "$.homepage", "homepage")
    if "license" in value:
        check_string(value["license"], errors, path, "$.license", "license")
    validate_localizations(value.get("localizations"), errors, path, "$.localizations")

    versions = value.get("versions")
    if not isinstance(versions, list):
        error(errors, path, "$.versions", "versions is required and must be an array")
        versions = []
    elif not versions:
        error(errors, path, "$.versions", "versions must not be empty")

    seen_versions: set[str] = set()
    valid_versions: list[str] = []
    for index, version in enumerate(versions):
        version_location = f"$.versions[{index}]"
        validate_version(version, errors, path, version_location)
        if isinstance(version, dict):
            text = version.get("version")
            if isinstance(text, str) and semver_parts(text) is not None:
                if text in seen_versions:
                    error(
                        errors,
                        path,
                        f"{version_location}.version",
                        f"duplicate version '{text}'",
                    )
                seen_versions.add(text)
                valid_versions.append(text)

    latest = value.get("latest_version")
    if not isinstance(latest, str) or semver_parts(latest) is None:
        error(errors, path, "$.latest_version", "latest_version must be valid SemVer")
    elif valid_versions:
        highest = valid_versions[0]
        for candidate in valid_versions[1:]:
            if compare_semver(candidate, highest) > 0:
                highest = candidate
        if latest != highest:
            error(
                errors,
                path,
                "$.latest_version",
                f"latest_version '{latest}' must equal the highest version '{highest}'",
            )


def load_plugin_files(errors: list[str]) -> dict[str, dict[str, Any]]:
    plugins: dict[str, dict[str, Any]] = {}
    if not PLUGINS_DIR.is_dir():
        error(errors, PLUGINS_DIR, "$", "plugins directory is missing")
        return plugins
    for path in sorted(PLUGINS_DIR.glob("*.json")):
        if path.name.startswith("."):
            continue
        value = parse_json(path, errors)
        if value is None:
            continue
        validate_plugin(value, errors, path)
        plugin_id = value.get("id") if isinstance(value, dict) else None
        if not isinstance(plugin_id, str):
            continue
        if path.stem != plugin_id:
            error(
                errors,
                path,
                "$.id",
                f"file name must be '{plugin_id}.json'",
            )
        if plugin_id in plugins:
            error(errors, path, "$.id", f"duplicate plugin id '{plugin_id}'")
            continue
        plugins[plugin_id] = value
    return plugins


def validate_examples(errors: list[str]) -> None:
    if not EXAMPLES_DIR.is_dir():
        return
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        if path.name.startswith("."):
            continue
        value = parse_json(path, errors)
        if value is None:
            continue
        validate_plugin(value, errors, path)


def validate_catalog(
    catalog: Any, errors: list[str], path: Path
) -> list[dict[str, Any]]:
    if not isinstance(catalog, dict):
        error(errors, path, "$", "catalog must be an object")
        return []
    unknown = sorted(set(catalog) - CATALOG_FIELDS)
    if unknown:
        error(errors, path, "$", f"unknown fields: {', '.join(unknown)}")
    if catalog.get("catalog_version") != 1:
        error(errors, path, "$.catalog_version", "catalog_version must be 1")
    repository = catalog.get("repository")
    if not isinstance(repository, dict):
        error(errors, path, "$.repository", "repository is required and must be an object")
    else:
        unknown = sorted(set(repository) - REPOSITORY_FIELDS)
        if unknown:
            error(
                errors,
                path,
                "$.repository",
                f"unknown fields: {', '.join(unknown)}",
            )
        check_string(repository.get("id"), errors, path, "$.repository.id", "repository.id")
        check_string(
            repository.get("name"), errors, path, "$.repository.name", "repository.name"
        )
        if "homepage" in repository:
            check_https_url(
                repository["homepage"],
                errors,
                path,
                "$.repository.homepage",
                "repository.homepage",
            )
    if "generated_at" in catalog and not isinstance(catalog["generated_at"], str):
        error(errors, path, "$.generated_at", "generated_at must be a string")
    plugins = catalog.get("plugins")
    if not isinstance(plugins, list):
        error(errors, path, "$.plugins", "plugins is required and must be an array")
        return []
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, plugin in enumerate(plugins):
        plugin_location = f"$.plugins[{index}]"
        validate_plugin(plugin, errors, path)
        if not isinstance(plugin, dict):
            continue
        plugin_id = plugin.get("id")
        if isinstance(plugin_id, str):
            if plugin_id in seen:
                error(
                    errors,
                    path,
                    f"{plugin_location}.id",
                    f"duplicate plugin id '{plugin_id}'",
                )
            seen.add(plugin_id)
        result.append(plugin)
    return result


def compare_sources(
    catalog_plugins: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    errors: list[str],
    path: Path,
) -> None:
    catalog_by_id: dict[str, dict[str, Any]] = {}
    for plugin in catalog_plugins:
        if isinstance(plugin, dict) and isinstance(plugin.get("id"), str):
            catalog_by_id[plugin["id"]] = plugin
    for plugin_id in sorted(set(catalog_by_id) - set(sources)):
        error(
            errors,
            path,
            "$.plugins",
            f"plugin '{plugin_id}' is in the catalog but has no plugins/{plugin_id}.json",
        )
    for plugin_id in sorted(set(sources) - set(catalog_by_id)):
        error(
            errors,
            PLUGINS_DIR / f"{plugin_id}.json",
            "$",
            f"plugin '{plugin_id}' is missing from catalog/index.json",
        )
    for plugin_id in sorted(set(sources) & set(catalog_by_id)):
        if sources[plugin_id] != catalog_by_id[plugin_id]:
            error(
                errors,
                PLUGINS_DIR / f"{plugin_id}.json",
                "$",
                "plugin entry differs from catalog/index.json; regenerate the catalog",
            )
    expected_order = sorted(catalog_by_id)
    actual_order = [
        plugin.get("id")
        for plugin in catalog_plugins
        if isinstance(plugin, dict) and isinstance(plugin.get("id"), str)
    ]
    if actual_order != expected_order and all(
        isinstance(item, str) for item in actual_order
    ):
        error(errors, path, "$.plugins", "plugins must be sorted by id")


def download_artifacts(catalog_plugins: list[dict[str, Any]], errors: list[str]) -> None:
    for plugin in catalog_plugins:
        if not isinstance(plugin, dict):
            continue
        plugin_id = plugin.get("id", "<unknown>")
        for version in plugin.get("versions", []):
            if not isinstance(version, dict):
                continue
            for artifact in version.get("artifacts", []):
                if not isinstance(artifact, dict):
                    continue
                url = artifact.get("url")
                if not is_https_url(url):
                    continue
                try:
                    request = urllib.request.Request(
                        url, headers={"User-Agent": "luban-notepad-store-validator"}
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        data = response.read(MAX_ARTIFACT_BYTES + 1)
                except OSError as exc:
                    errors.append(f"{plugin_id}: artifact download failed: {exc}")
                    continue
                if len(data) > MAX_ARTIFACT_BYTES:
                    errors.append(
                        f"{plugin_id}: artifact is larger than {MAX_ARTIFACT_BYTES} bytes"
                    )
                    continue
                size = artifact.get("size")
                if isinstance(size, int) and len(data) != size:
                    errors.append(
                        f"{plugin_id}: artifact size is {len(data)}, expected {size}"
                    )
                digest = hashlib.sha256(data).hexdigest()
                expected = str(artifact.get("sha256", "")).lower()
                if digest != expected:
                    errors.append(
                        f"{plugin_id}: artifact SHA-256 is {digest}, expected {expected}"
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download",
        action="store_true",
        help="download each HTTPS artifact and verify its size and SHA-256",
    )
    args = parser.parse_args()

    errors: list[str] = []
    sources = load_plugin_files(errors)
    catalog_plugins: list[dict[str, Any]] = []
    if not CATALOG_PATH.is_file():
        error(errors, CATALOG_PATH, "$", "catalog/index.json is missing")
    else:
        catalog = parse_json(CATALOG_PATH, errors, MAX_CATALOG_BYTES)
        if catalog is not None:
            catalog_plugins = validate_catalog(catalog, errors, CATALOG_PATH)
            compare_sources(catalog_plugins, sources, errors, CATALOG_PATH)
    validate_examples(errors)
    if args.download and not errors:
        download_artifacts(catalog_plugins, errors)

    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        print(f"validation failed with {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"validation passed ({len(sources)} plugin(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
