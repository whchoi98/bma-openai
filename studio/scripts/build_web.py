#!/usr/bin/env python3
"""Package the separate Web Function and worker without keys or Python data."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build():
    files = {}
    for path in (ROOT / "studio/web").rglob("*"):
        if path.is_file() and "node_modules" not in path.parts:
            files[str(path.relative_to(ROOT))] = path
    for name in ["studio/package.json", "web/bma.js", "web/contract.json"]:
        files[name] = ROOT / name
    production = subprocess.check_output(
        ["npm", "ls", "--omit=dev", "--all", "--parseable"], cwd=ROOT / "web", text=True
    )
    for directory in set(production.splitlines()):
        package = Path(directory)
        if not package.is_relative_to(ROOT / "web/node_modules"):
            continue
        for path in package.rglob("*"):
            if path.is_file() and "node_modules" not in path.relative_to(package).parts:
                files[str(path.relative_to(ROOT / "web"))] = path
    output = ROOT / "artifacts/studio/web-function.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        package = json.loads((ROOT / "web/package.json").read_text())
        package["name"] = "ai-document-studio"
        archive.writestr("package.json", json.dumps(package))
        archive.writestr("index.js", 'import "./studio/web/index.js";\n')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert "studio/web/worker.js" in archive.namelist()
        assert "studio/web/static/fonts/NanumSquareB.otf" in archive.namelist()
        assert not any("/artifacts/" in name or name.endswith(".env") for name in archive.namelist())
    result = {"artifact": str(output.relative_to(ROOT)), "files": len(files) + 2,
              "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (output.parent / "web-build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    build()
