"""Frozen development / reporting split of the 25 public solved examples.

Why this exists and why it is an M0 deliverable: a split created *after* tuning
proves nothing. The manifest is generated once, written to
`code/evaluation/split_manifest.json`, and thereafter only ever verified. Any
drift -- a changed salt, a changed sample file, a hand-edited id list -- is an
error, not a silent regeneration.

Assignment is deterministic and documented rather than random: order the request
ids by `sha256(SALT:request_id)` and take the first `DEV_SIZE` for development.
No seeded RNG is involved, so the split is reproducible on any machine and any
Python version.

**Portability (`SPLIT_VERSION` 2).** The gating identity of
`sample_requests.csv` is `sample_sha256`, a *canonical* content hash
(`buy_or_wait.data.canonical_content_sha256`) that normalizes CRLF/CR to LF
before hashing, so a manifest frozen on one OS still verifies after a clone
that checks the file out with different line endings elsewhere -- Linux CI or
a browser-based evaluator, in particular. The raw byte hash is retained
separately as `sample_sha256_raw` for provenance only; it is never compared
during verification, because it is expected to differ across checkouts. An
actual content change (any byte difference that survives newline
normalization) still changes `sample_sha256` and is still rejected.

**Exposure disclosure.** These 25 rows are public examples, not hidden ground
truth, and prior sessions on this project have already read all 25 while
establishing output conventions. Numbers computed on the reporting subset must
be labelled "fixed public-sample reporting subset, prior exposure disclosed",
never "held-out" or "unbiased".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SPLIT_VERSION = 2
SPLIT_SALT = "buy-or-wait-2026-09"
SPLIT_ALGORITHM = "sha256(salt:request_id) ascending"
DEV_SIZE = 10

MANIFEST_PATH = Path(__file__).resolve().parent / "split_manifest.json"


class SplitError(RuntimeError):
    """Raised when the on-disk manifest disagrees with the computed split."""


@dataclass(frozen=True)
class Split:
    dev: tuple[str, ...]
    report: tuple[str, ...]
    version: int
    salt: str
    algorithm: str
    sample_sha256: str          # canonical content identity -- the gate
    sample_sha256_raw: str = "" # raw-byte identity -- provenance only

    def assert_disjoint(self) -> None:
        overlap = set(self.dev) & set(self.report)
        if overlap:
            raise SplitError(f"development and reporting subsets overlap: {sorted(overlap)}")

    def subset(self, name: str) -> tuple[str, ...]:
        if name == "dev":
            return self.dev
        if name == "report":
            return self.report
        raise SplitError(f"unknown subset {name!r} (expected 'dev' or 'report')")


def _rank(request_id: str) -> str:
    return hashlib.sha256(f"{SPLIT_SALT}:{request_id}".encode("utf-8")).hexdigest()


def compute_split(request_ids: Sequence[str], sample_sha256: str,
                  sample_sha256_raw: str = "") -> Split:
    """Derive the split from the sample request ids. Pure and deterministic.

    `sample_sha256` is the canonical (newline-normalized) content hash and is
    the only one compared during verification. `sample_sha256_raw` is stored
    only for provenance and is expected to differ across a CRLF/LF checkout.
    """
    unique = sorted(set(request_ids))
    if len(unique) != len(request_ids):
        raise SplitError("duplicate request_id in sample requests")
    if len(unique) <= DEV_SIZE:
        raise SplitError(f"need more than {DEV_SIZE} samples to form a reporting subset, got {len(unique)}")
    ordered = sorted(unique, key=_rank)
    split = Split(
        dev=tuple(sorted(ordered[:DEV_SIZE])),
        report=tuple(sorted(ordered[DEV_SIZE:])),
        version=SPLIT_VERSION,
        salt=SPLIT_SALT,
        algorithm=SPLIT_ALGORITHM,
        sample_sha256=sample_sha256,
        sample_sha256_raw=sample_sha256_raw,
    )
    split.assert_disjoint()
    return split


def _as_dict(split: Split) -> dict:
    return {
        "version": split.version,
        "salt": split.salt,
        "algorithm": split.algorithm,
        "sample_requests_sha256": split.sample_sha256,
        "sample_requests_sha256_raw": split.sample_sha256_raw,
        "dev": list(split.dev),
        "report": list(split.report),
    }


def manifest_fingerprint(split: Split) -> str:
    """Short stable hash of the manifest, printed in the evaluation header so a
    reader can tell at a glance which split produced a number."""
    blob = json.dumps(_as_dict(split), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def write_manifest(split: Split, path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_as_dict(split), indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path = MANIFEST_PATH) -> Split:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "sample_requests_sha256" not in payload:
        raise SplitError(f"{path}: manifest is missing sample_requests_sha256")
    if payload.get("version") == 1:
        raise SplitError(
            f"{path}: manifest is SPLIT_VERSION 1 (raw-byte identity only). "
            "Migrate deliberately with the version-2 canonical hash "
            "(buy_or_wait.data.canonical_content_sha256) rather than deleting it."
        )
    split = Split(
        dev=tuple(payload["dev"]),
        report=tuple(payload["report"]),
        version=payload["version"],
        salt=payload["salt"],
        algorithm=payload["algorithm"],
        sample_sha256=payload["sample_requests_sha256"],
        sample_sha256_raw=payload.get("sample_requests_sha256_raw", ""),
    )
    split.assert_disjoint()
    return split


def ensure_split(request_ids: Sequence[str], sample_sha256: str,
                 path: Path = MANIFEST_PATH, *, allow_create: bool = True,
                 sample_sha256_raw: str = "") -> Split:
    """Return the frozen split, creating it exactly once.

    If the manifest exists it is verified against a freshly computed split and
    against the sample file's *canonical* hash. Disagreement raises rather
    than rewriting -- silently regenerating a split after tuning is the
    failure mode this whole module exists to prevent. `sample_sha256_raw` is
    never part of that comparison: it is expected to differ across a
    CRLF/LF checkout and is recorded for provenance only.
    """
    computed = compute_split(request_ids, sample_sha256, sample_sha256_raw)
    if not path.exists():
        if not allow_create:
            raise SplitError(f"split manifest missing at {path}")
        write_manifest(computed, path)
        return computed

    stored = load_manifest(path)
    problems: list[str] = []
    if stored.version != computed.version:
        problems.append(f"version {stored.version} != {computed.version}")
    if stored.salt != computed.salt:
        problems.append(f"salt {stored.salt!r} != {computed.salt!r}")
    if stored.sample_sha256 != computed.sample_sha256:
        problems.append("sample_requests.csv has changed since the split was frozen "
                         "(canonical content hash differs)")
    if stored.dev != computed.dev or stored.report != computed.report:
        problems.append("stored id lists differ from the recomputed split")
    if problems:
        raise SplitError(
            "frozen split manifest disagrees with the computed split: "
            + "; ".join(problems)
            + f"\n  manifest: {path}\n  Resolve deliberately; do not delete the manifest to make this pass."
        )
    return stored
