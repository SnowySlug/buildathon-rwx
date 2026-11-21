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
    with urllib.request.urlopen(URL, timeout=90) as response:
        content = response.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        raise RuntimeError("Pinned source archive unexpectedly large")
    extracted = set()
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != f"sqlglot-{COMMIT}":
                raise RuntimeError("Unexpected source archive prefix")
            relative = PurePosixPath(*parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Unsafe source archive path")
            name = relative.as_posix()
            if name not in expected:
                continue
            if not member.isfile():
                raise RuntimeError("Expected regular Python source file")
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != expected[name]:
                raise RuntimeError(f"Pinned source/map mismatch: {name}")
            destination = SOURCE / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o644)
            extracted.add(name)
    if extracted != set(expected):
        raise RuntimeError("Pinned source archive missing mapped source files")
    print(f"Verified {len(extracted)} Python files against pristine map")


if __name__ == "__main__":
    main()
