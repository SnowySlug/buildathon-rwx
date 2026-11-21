"""Fetch only the competition-permitted pinned sqlglot source at build time."""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
URL = f"https://github.com/tobymao/sqlglot/archive/{COMMIT}.tar.gz"
SOURCE = Path("/opt/sqlglot")


def main():
    coverage = json.loads(Path("/app/coverage.json").read_text("utf-8"))
    expected = coverage["source_python_sha256"]
    needed = set(expected) | set(coverage["collection_opened"])
    if coverage.get("encoding") == "outer-function-bitsets-v1":
        paths = coverage["paths"]
        for record in coverage["tests"].values():
            needed.update(paths[index] for index in record[1])
    else:
        for record in coverage["tests"].values():
            needed.update(record["opened"])
    with urllib.request.urlopen(URL, timeout=90) as response:
        content = response.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        raise RuntimeError("Pinned source archive unexpectedly large")
    extracted = set()
    source_files = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != f"sqlglot-{COMMIT}":
                raise RuntimeError("Unexpected source archive prefix")
            relative = PurePosixPath(*parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Unsafe source archive path")
            name = relative.as_posix()
            if name not in needed:
                continue
            if not member.isfile():
                if name in expected:
                    raise RuntimeError("Expected regular Python source file")
                continue
            data = archive.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            if name in expected and digest != expected[name]:
                raise RuntimeError(f"Pinned source/map mismatch: {name}")
            destination = SOURCE / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o644)
            extracted.add(name)
            source_files[name] = digest
    if not set(expected).issubset(extracted):
        raise RuntimeError("Pinned source archive missing mapped source files")
    Path("/app/source_files.json").write_text(json.dumps(source_files, separators=(",", ":")), encoding="utf-8")
    print(f"Verified {len(expected)} Python files; indexed {len(source_files)} pinned dependency files")


if __name__ == "__main__":
    main()
