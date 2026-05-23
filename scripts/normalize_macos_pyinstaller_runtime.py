#!/usr/bin/env python3
"""Normalize PyInstaller-collected macOS frameworks for code signing.

PyInstaller can collect Python.framework into an onedir payload as a copied
framework-shaped directory instead of the standard symlink layout. Apple
codesign/notary then treats the duplicated ``Python.framework/Python`` and
``Versions/Current`` directories as a bundle but cannot validate the resource
seal, producing errors such as::

    code has no resources but signature indicates they must be present

This script rewrites those copied framework layouts back into the canonical
macOS framework symlink form before signing and zipping the runtime artifact.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _replace_with_symlink(path: Path, target: str) -> None:
    _remove_path(path)
    os.symlink(target, path)


def _framework_version_dir(framework: Path) -> Path | None:
    versions = framework / "Versions"
    if not versions.is_dir():
        return None
    candidates = [
        child
        for child in versions.iterdir()
        if child.is_dir() and not child.is_symlink() and child.name != "Current"
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Prefer Python-style numeric versions when there are auxiliary directories.
    numeric = [child for child in candidates if child.name[:1].isdigit()]
    if len(numeric) == 1:
        return numeric[0]
    names = ", ".join(sorted(child.name for child in candidates))
    raise RuntimeError(f"{framework} has multiple framework version directories: {names}")


def normalize_framework(framework: Path) -> bool:
    version_dir = _framework_version_dir(framework)
    if version_dir is None:
        return False

    executable_name = framework.stem
    executable = version_dir / executable_name
    resources = version_dir / "Resources"
    if not executable.exists():
        return False

    _replace_with_symlink(framework / executable_name, f"Versions/Current/{executable_name}")
    if resources.exists():
        _replace_with_symlink(framework / "Resources", "Versions/Current/Resources")
    else:
        _remove_path(framework / "Resources")

    _replace_with_symlink(framework / "Versions" / "Current", version_dir.name)
    return True


def normalize_runtime(root: Path) -> int:
    normalized = 0
    for framework in sorted(root.rglob("*.framework")):
        if normalize_framework(framework):
            normalized += 1
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_dir", type=Path, help="PyInstaller onedir runtime directory")
    args = parser.parse_args()

    runtime_dir = args.runtime_dir
    if not runtime_dir.is_dir():
        raise SystemExit(f"runtime directory not found: {runtime_dir}")

    normalized = normalize_runtime(runtime_dir)
    print(f"normalized {normalized} macOS framework directories under {runtime_dir}")


if __name__ == "__main__":
    main()
