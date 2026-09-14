#!/usr/bin/env python3
#
# Build a Checkmk extension package (.mkp) from the repository.
#
# Copyright (C) 2026 The checkmk-iosxe-capacity authors
# License: GNU General Public License v2 - see LICENSE
"""Package the repository into ``dist/<name>-<version>.mkp``.

An ``.mkp`` is a gzipped tar that contains

    info            the manifest as a Python literal (what Checkmk reads)
    info.json       the same manifest as JSON
    <part>.tar      one tar per package part, here cmk_addons_plugins.tar

The plugin files sit below ``cmk_addons/plugins``, the same path they take
below a site's ``~/local/lib/python3/``, so the tree can also be copied into
a site by hand for development.

Usage:

    python3 scripts/build_mkp.py                    # build dist/*.mkp
    python3 scripts/build_mkp.py --update-manifest  # rescan the tree, then build
    python3 scripts/build_mkp.py --check            # verify only, build nothing
"""

from __future__ import annotations

import argparse
import io
import json
import pprint
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Package part -> directory below the repository root. Only parts that exist
# are packaged.
PART_PATHS: dict[str, str] = {
    "cmk_addons_plugins": "cmk_addons/plugins",
}

# Files that never belong in a package. The AppleDouble entries matter: a
# ._name file copied from a Mac into a site breaks the replication snapshot.
IGNORED_NAMES = {".DS_Store", "__pycache__", ".gitkeep", ".mypy_cache", ".ruff_cache"}


def _is_ignored(path: Path) -> bool:
    return any(
        part in IGNORED_NAMES or part.endswith(".pyc") or part.startswith("._")
        for part in path.parts
    )


def scan_parts(root: Path) -> dict[str, list[str]]:
    """Return {part: [paths relative to the part directory]} for existing parts."""
    parts: dict[str, list[str]] = {}
    for part, rel_dir in PART_PATHS.items():
        base = root / rel_dir
        if not base.is_dir():
            continue
        files = [
            str(path.relative_to(base))
            for path in base.rglob("*")
            if path.is_file() and not _is_ignored(path.relative_to(base))
        ]
        if files:
            parts[part] = sorted(files)
    return parts


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=4, sort_keys=True)
        handle.write("\n")


def check_manifest(manifest: dict[str, Any], scanned: dict[str, list[str]]) -> list[str]:
    """Return a list of differences between the manifest and the tree."""
    problems = []
    listed = manifest.get("files", {})
    for part in sorted(set(listed) | set(scanned)):
        want = set(scanned.get(part, []))
        have = set(listed.get(part, []))
        for missing in sorted(want - have):
            problems.append(f"{part}: {missing} is not listed in the manifest")
        for stale in sorted(have - want):
            problems.append(f"{part}: {stale} is listed but does not exist")
    return problems


def _tar_info(name: str, source: Path, size: int, mtime: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = mtime
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if source.stat().st_mode & 0o100 else 0o644
    return info


def build_part_tar(root: Path, part: str, files: list[str]) -> bytes:
    base = root / PART_PATHS[part]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for rel in files:
            source = base / rel
            if not source.is_file():
                raise SystemExit(
                    f"error: {source} is listed in the manifest but does not exist"
                )
            data = source.read_bytes()
            info = _tar_info(rel, source, len(data), int(source.stat().st_mtime))
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_mkp(root: Path, manifest: dict[str, Any], outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / f"{manifest['name']}-{manifest['version']}.mkp"

    members: list[tuple[str, bytes]] = [
        ("info", pprint.pformat(manifest, width=99).encode("utf-8") + b"\n"),
        ("info.json", json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")),
    ]
    for part, files in sorted(manifest.get("files", {}).items()):
        if files:
            members.append((f"{part}.tar", build_part_tar(root, part, files)))

    now = int(time.time())
    with tarfile.open(target, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = now
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the iosxe_capacity .mkp")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "package.manifest",
        help="path to the package manifest (default: package.manifest)",
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="rewrite the file list in the manifest from the tree",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="output directory (default: dist/)",
    )
    parser.add_argument(
        "--check", action="store_true", help="only verify the manifest, do not build"
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    scanned = scan_parts(REPO_ROOT)
    if not scanned:
        raise SystemExit("error: no packageable files found below cmk_addons/")

    if args.update_manifest:
        manifest["files"] = scanned
        save_manifest(args.manifest, manifest)
        print(f"updated {args.manifest.relative_to(REPO_ROOT)}")

    problems = check_manifest(manifest, scanned)
    if problems:
        for problem in problems:
            sys.stderr.write(f"error: {problem}\n")
        sys.stderr.write("run 'build_mkp.py --update-manifest' to fix the file list\n")
        return 1

    total = sum(len(f) for f in manifest["files"].values())
    if args.check:
        print(f"manifest OK: {total} files, version {manifest['version']}")
        return 0

    target = build_mkp(REPO_ROOT, manifest, args.outdir)
    print(f"wrote {target} ({total} files, {target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
