#!/usr/bin/env python3
"""Copy a verified, pinned ARM64 Codex binary into the Runtime build context."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.164.0"


def prepare(source: Path):
    source = source.resolve()
    with source.open("rb") as stream:
        header = stream.read(64)
    if header[:4] != b"\x7fELF" or header[5] != 1 or struct.unpack("<H", header[18:20])[0] != 183:
        raise ValueError("Runtime image requires a Linux ARM64 ELF Codex binary.")
    version = subprocess.check_output([str(source), "--version"], text=True, timeout=10).strip()
    if version != f"codex-cli {VERSION}":
        raise ValueError(f"Expected Codex {VERSION}; got {version}. Review the BMA protocol before changing the pin.")
    help_text = subprocess.check_output([str(source), "exec-server", "--help"], text=True, timeout=10)
    if not all(flag in help_text for flag in ["--remote", "--environment-id", "--aws-sigv4"]):
        raise ValueError("This binary does not expose the documented BMA exec-server flags.")
    destination = ROOT / "runtime/bin/codex"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o555)
    with destination.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"codex_version": VERSION, "architecture": "linux/arm64", "sha256": checksum}
    (destination.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="Official installed Linux ARM64 Codex ELF binary.")
    args = parser.parse_args()
    source = args.source
    if source is None:
        executable = shutil.which("codex")
        if executable is None:
            parser.error("Install official Codex 0.164.0 or supply --source.")
        resolved = Path(executable).resolve()
        with resolved.open("rb") as stream:
            is_elf = stream.read(4) == b"\x7fELF"
        source = resolved if is_elf else (
            resolved.parents[1] / "node_modules/@openai/codex-linux-arm64/vendor/aarch64-unknown-linux-musl/bin/codex"
        )
    print(json.dumps(prepare(source), indent=2))


if __name__ == "__main__":
    main()
