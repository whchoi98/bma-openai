#!/usr/bin/env python3
"""Build a Node.js-only Web Function ZIP without including credentials or local Python environments."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    web = ROOT / "web"
    if not (web / "node_modules/@aws-sdk/client-sts").is_dir():
        raise SystemExit("Run npm ci --ignore-scripts --prefix web first.")
    subprocess.run(["npm", "run", "build"], cwd=web, check=True)
    artifact = ROOT / "artifacts/web-function.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    sources = [(p, p.relative_to(web)) for p in sorted(web.glob("*.js"))]
    sources += [(web / name, Path(name)) for name in ["package.json", "package-lock.json", "contract.json", "sample-data.json"]]
    production = subprocess.check_output(
        ["npm", "ls", "--omit=dev", "--all", "--parseable"], cwd=web, text=True
    )
    for directory in sorted(set(production.splitlines())):
        package = Path(directory)
        if package == web or not package.is_relative_to(web / "node_modules"):
            continue
        for path in sorted(package.rglob("*")):
            if path.is_file() and "node_modules" not in path.relative_to(package).parts:
                sources.append((path, path.relative_to(web)))
    static = ROOT / "webapp/static"
    sources += [(path, Path("static") / path.relative_to(static))
                for path in sorted(static.rglob("*")) if path.is_file()]
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path, target in sources:
            package.write(path, target)
    with zipfile.ZipFile(artifact) as package:
        assert package.testzip() is None
        names = package.namelist()
        assert "index.js" in names and "static/app.js" in names
        assert "static/fonts/NanumSquareB.otf" in names
        assert "static/fonts/OFL.txt" in names
        assert "static/report.css" in names
        assert "node_modules/react-markdown/package.json" in names
        assert not any(name.startswith("node_modules/esbuild/") for name in names)
        assert not any(".env" == Path(name).name or name.startswith(".venv/") for name in names)
    with artifact.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"artifact": str(artifact.relative_to(ROOT)), "sha256": checksum, "files": len(sources),
              "runtime": "nodejs24.x", "bytes": artifact.stat().st_size}
    (artifact.parent / "web-build.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
