#!/usr/bin/env python3
"""Sign a hermes-agent-cn runtime manifest with Ed25519.

The hermes-cn-desktop-v2 client (see ``src/process/runtime.rs``) verifies
the signature against the public key it was built with. The canonical
payload concatenated with ``\\n`` matches what the Rust side reconstructs
in ``signature_payload()`` — keep the field order in sync.

Inputs are passed via flags so the GitHub Actions workflow can wire them
up without env-var games. The private key is read from
``RUNTIME_SIGN_PRIVATE_KEY_PEM`` (env) by default — never accept it on
argv where it would land in process listings.

Usage:
    python scripts/sign_runtime_manifest.py \\
        --channel stable \\
        --version 0.13.0+cn.20260516 \\
        --platform win32 \\
        --arch x64 \\
        --artifact-url https://github.com/.../runtime-win32-x64.zip \\
        --artifact-path dist/runtime-win32-x64.zip \\
        --upstream-repo Eynzof/hermes-agent-cn \\
        --upstream-commit "$GITHUB_SHA" \\
        --min-app-version 0.1.0 \\
        --output dist/manifest-win32-x64.json
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
except ImportError:
    raise SystemExit(
        "scripts/sign_runtime_manifest.py needs `cryptography` "
        "(pip install cryptography)."
    )


# Field order MUST match `signature_payload()` in
# hermes-cn-desktop-v2/src/process/runtime.rs. Any reorder here is a
# silent verification failure on every desktop install — change both
# sides together or not at all.
_PAYLOAD_FIELDS = (
    "channel",
    "platform",
    "arch",
    "version",
    "artifactUrl",
    "sha256",
    "upstreamRepo",
    "upstreamCommit",
)


def _sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_private_key() -> Ed25519PrivateKey:
    pem = os.environ.get("RUNTIME_SIGN_PRIVATE_KEY_PEM")
    if not pem:
        raise SystemExit(
            "RUNTIME_SIGN_PRIVATE_KEY_PEM is not set. In GitHub Actions, wire "
            "the repository secret to the workflow env block; locally, "
            "export it from your encrypted key store. Never put the key on "
            "argv (it'd leak via process listings)."
        )
    # Unwrap "\n" → newline so secrets pasted as one-liners work.
    pem = pem.replace("\\n", "\n").encode()
    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("RUNTIME_SIGN_PRIVATE_KEY_PEM is not an Ed25519 key.")
    return key


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channel", required=True, help="stable | beta | canary | ...")
    p.add_argument("--version", required=True)
    p.add_argument("--platform", required=True, choices=("win32", "darwin", "linux"))
    p.add_argument("--arch", required=True, choices=("x64", "arm64"))
    p.add_argument("--artifact-url", required=True, help="HTTPS URL clients fetch")
    p.add_argument(
        "--artifact-path",
        required=True,
        type=Path,
        help="Local path to the zip — used to compute sha256",
    )
    p.add_argument("--upstream-repo", required=True, help="org/name slug")
    p.add_argument("--upstream-commit", required=True, help="commit SHA")
    p.add_argument("--min-app-version", default=None, help="desktop client floor")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    if not args.artifact_path.is_file():
        raise SystemExit(f"artifact zip not found: {args.artifact_path}")

    if not args.artifact_url.startswith("https://"):
        # Rust side rejects non-https; fail fast here so CI doesn't ship
        # a manifest the client will refuse.
        raise SystemExit(f"artifact_url must be https:, got {args.artifact_url!r}")

    sha256 = _sha256_hex(args.artifact_path)
    print(f"sha256({args.artifact_path.name}) = {sha256}", file=sys.stderr)

    manifest = {
        "channel": args.channel,
        "platform": args.platform,
        "arch": args.arch,
        "version": args.version,
        "artifactUrl": args.artifact_url,
        "sha256": sha256,
        "upstreamRepo": args.upstream_repo,
        "upstreamCommit": args.upstream_commit,
    }
    if args.min_app_version:
        manifest["minAppVersion"] = args.min_app_version
    manifest["createdAt"] = (
        _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    # Build canonical payload + sign. signature_payload() in runtime.rs
    # concatenates these eight fields with \n separators.
    payload = "\n".join(str(manifest[f]) for f in _PAYLOAD_FIELDS).encode()
    key = _load_private_key()
    signature = key.sign(payload)
    manifest["signature"] = base64.standard_b64encode(signature).decode()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
