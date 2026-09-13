"""Build `code.zip` for submission from an explicit allowlist.

    python code/package.py

Zips this directory's runnable contents at the *archive root* -- so the
archive contains `evaluation/usage_report.md`, never `code/evaluation/...` --
per `docs/IMPLEMENTATION_PLAN.md` section 9. Excludes caches, prior run
artifacts, and anything not on the allowlist (secrets, local settings,
virtual environments). Warns rather than silently packaging a still-empty
`evaluation/usage_report.md`.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
OUTPUT_ZIP = REPO_ROOT / "code.zip"

# Directories packaged whole, minus the excluded names below.
INCLUDE_DIRS = ("buy_or_wait", "prompts", "evaluation", "tests")
INCLUDE_FILES = ("main.py", "package.py", "README.md")

EXCLUDE_DIR_NAMES = {"__pycache__", "runs", ".pytest_cache"}
EXCLUDE_FILE_NAMES = {"extraction_cache.json"}
EXCLUDE_SUFFIXES = {".pyc"}


def _iter_files():
    for name in INCLUDE_FILES:
        path = CODE_DIR / name
        if path.exists():
            yield path
    for dirname in INCLUDE_DIRS:
        base = CODE_DIR / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EXCLUDE_DIR_NAMES for part in path.relative_to(CODE_DIR).parts):
                continue
            if path.name in EXCLUDE_FILE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
                continue
            yield path


def build(out_path: Path = OUTPUT_ZIP) -> Path:
    files = sorted(set(_iter_files()))
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=str(path.relative_to(CODE_DIR)))
    return out_path


def main() -> int:
    usage_report = CODE_DIR / "evaluation" / "usage_report.md"
    if not usage_report.exists() or not usage_report.read_text(encoding="utf-8").strip():
        print("WARNING: evaluation/usage_report.md is empty. Per the submission contract "
              "it must reflect the final full-dataset run before you submit this archive.",
              file=sys.stderr)

    out_path = build()
    print(f"wrote {out_path}")
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
    print(f"{len(names)} files:")
    for name in names:
        print(f"  {name}")
    if "evaluation/usage_report.md" not in names:
        print("ERROR: evaluation/usage_report.md is missing from the archive root path.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
