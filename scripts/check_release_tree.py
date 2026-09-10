"""Check the Git index for generated files and recognizable credential formats."""

import hashlib
import re
import subprocess
from pathlib import Path


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    failures, checksums = [], []
    patterns = [
        rb"gh[pousr]_[A-Za-z0-9]{30,}",
        rb"github_pat_[A-Za-z0-9_]{40,}",
        rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
        rb"(?i)postgres(?:ql)?://[^\s:@]+:(?!ci-test-only@|password@|your-password@)[^\s@]{12,}@",
    ]
    for name in filter(None, paths):
        path = Path(name)
        if (
            any(
                part
                in (
                    ".venv",
                    "__pycache__",
                    "staticfiles",
                    "node_modules",
                    "logs",
                    ".railway-state",
                )
                for part in path.parts
            )
            or path.suffix in (".sqlite3", ".pyc", ".zip")
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            failures.append(f"Generated or sensitive path staged: {name}")
        data = subprocess.check_output(["git", "show", ":" + name])
        if path.suffix in (
            ".py",
            ".js",
            ".md",
            ".json",
            ".yml",
            ".yaml",
            ".toml",
            ".txt",
        ):
            if any(re.search(pattern, data) for pattern in patterns):
                failures.append(f"Credential pattern requires review: {name}")
        if name != "FINAL_SHA256SUMS.txt":
            checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    if failures:
        print("\n".join(failures))
        return 1
    Path("FINAL_SHA256SUMS.txt").write_text(
        "".join(checksums), encoding="utf-8", newline="\n"
    )
    print(
        f"PASS: {len(checksums)} staged files; no forbidden generated paths or recognized credentials. FINAL_SHA256SUMS.txt written from index bytes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
