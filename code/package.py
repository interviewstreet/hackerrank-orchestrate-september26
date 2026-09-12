"""Build the submission code.zip.

    python package.py                # writes ../code.zip

The archive holds the contents of `code/` at its top level, so
`evaluation/usage_report.md` sits exactly where the submission requires it.
Secrets, caches, virtual environments and the dataset are excluded, and the
script refuses to build if anything that looks like a credential slipped in.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from config import CODE_DIR, REPO_ROOT

EXCLUDED_DIRS = {".cache", "__pycache__", ".git", "venv", ".venv", ".pytest_cache"}
EXCLUDED_NAMES = {".env", ".DS_Store", "code.zip"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log"}

REQUIRED = ("main.py", "README.md", "requirements.txt", "evaluation/usage_report.md")

# Anything resembling a live key blocks the build.
SECRET_PATTERN = re.compile(
    r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|"
    r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,})",
    re.IGNORECASE,
)


def included_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(CODE_DIR.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(CODE_DIR).parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def scan_for_secrets(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        if path.suffix not in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in SECRET_PATTERN.finditer(text):
            line = text[: match.start()].count("\n") + 1
            findings.append(f"{path.relative_to(CODE_DIR)}:{line}")
    return findings


def main() -> None:
    files = included_files()
    relative = {str(p.relative_to(CODE_DIR)) for p in files}

    missing = [name for name in REQUIRED if name not in relative]
    if missing:
        print("refusing to package -- missing required file(s):")
        for name in missing:
            print(f"  - {name}")
        if "evaluation/usage_report.md" in missing:
            print("\nRun `python main.py` first; it writes the usage report.")
        raise SystemExit(1)

    leaks = scan_for_secrets(files)
    if leaks:
        print("refusing to package -- possible credential(s) found:")
        for leak in leaks:
            print(f"  - {leak}")
        raise SystemExit(1)

    target = REPO_ROOT / "code.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(CODE_DIR))

    size_kb = target.stat().st_size / 1024
    print(f"wrote {target} ({len(files)} files, {size_kb:.0f} KB)")
    print("contents check: " + ", ".join(REQUIRED) + " all present")
    print("excluded: .env, .cache, __pycache__, virtualenvs, logs")


if __name__ == "__main__":
    sys.exit(main())
