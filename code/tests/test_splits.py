"""The frozen development/reporting split: determinism, disjointness, and
refusal to silently regenerate after tuning."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.data import canonical_content_sha256, file_sha256, load_dataset  # noqa: E402
from evaluation.splits import (  # noqa: E402
    DEV_SIZE,
    SplitError,
    compute_split,
    ensure_split,
    load_manifest,
    manifest_fingerprint,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATASET = REPO_ROOT / "dataset"

IDS = tuple(f"request_{i:02d}" for i in range(1, 26))
SHA = "0" * 64


class ComputeTests(unittest.TestCase):
    def test_is_deterministic(self):
        self.assertEqual(compute_split(IDS, SHA), compute_split(IDS, SHA))

    def test_is_independent_of_input_order(self):
        self.assertEqual(compute_split(IDS, SHA), compute_split(tuple(reversed(IDS)), SHA))

    def test_sizes_and_disjointness(self):
        split = compute_split(IDS, SHA)
        self.assertEqual(len(split.dev), DEV_SIZE)
        self.assertEqual(len(split.report), len(IDS) - DEV_SIZE)
        self.assertEqual(set(split.dev) & set(split.report), set())
        self.assertEqual(set(split.dev) | set(split.report), set(IDS))
        split.assert_disjoint()

    def test_assert_disjoint_raises_on_overlap(self):
        good = compute_split(IDS, SHA)
        leaked = type(good)(dev=good.dev, report=good.report + (good.dev[0],),
                            version=good.version, salt=good.salt,
                            algorithm=good.algorithm, sample_sha256=good.sample_sha256)
        with self.assertRaises(SplitError):
            leaked.assert_disjoint()

    def test_rejects_duplicates_and_tiny_inputs(self):
        with self.assertRaises(SplitError):
            compute_split(IDS + (IDS[0],), SHA)
        with self.assertRaises(SplitError):
            compute_split(IDS[:DEV_SIZE], SHA)

    def test_subset_lookup(self):
        split = compute_split(IDS, SHA)
        self.assertEqual(split.subset("dev"), split.dev)
        self.assertEqual(split.subset("report"), split.report)
        with self.assertRaises(SplitError):
            split.subset("holdout")


class ManifestTests(unittest.TestCase):
    def path(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "split_manifest.json"

    def test_creates_once_then_verifies(self):
        path = self.path()
        first = ensure_split(IDS, SHA, path)
        self.assertTrue(path.exists())
        second = ensure_split(IDS, SHA, path)
        self.assertEqual(first, second)

    def test_refuses_to_create_when_not_allowed(self):
        with self.assertRaises(SplitError):
            ensure_split(IDS, SHA, self.path(), allow_create=False)

    def test_detects_a_hand_edited_manifest(self):
        path = self.path()
        split = ensure_split(IDS, SHA, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["dev"], payload["report"] = payload["report"][:DEV_SIZE], payload["dev"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(SplitError) as ctx:
            ensure_split(IDS, SHA, path)
        self.assertIn("differ from the recomputed split", str(ctx.exception))
        self.assertIn("do not delete the manifest", str(ctx.exception))
        del split

    def test_detects_changed_sample_file(self):
        path = self.path()
        ensure_split(IDS, SHA, path)
        with self.assertRaises(SplitError) as ctx:
            ensure_split(IDS, "f" * 64, path)
        self.assertIn("sample_requests.csv has changed", str(ctx.exception))

    def test_detects_changed_id_population(self):
        path = self.path()
        ensure_split(IDS, SHA, path)
        with self.assertRaises(SplitError):
            ensure_split(IDS + ("request_26",), SHA, path)

    def test_fingerprint_is_stable_and_changes_with_content(self):
        a = compute_split(IDS, SHA)
        b = compute_split(IDS, "a" * 64)
        self.assertEqual(manifest_fingerprint(a), manifest_fingerprint(compute_split(IDS, SHA)))
        self.assertNotEqual(manifest_fingerprint(a), manifest_fingerprint(b))

    def test_round_trips_through_disk(self):
        path = self.path()
        split = compute_split(IDS, SHA)
        write_manifest(split, path)
        self.assertEqual(load_manifest(path), split)


@unittest.skipUnless(REAL_DATASET.is_dir(), "shipped dataset not present")
class RealSplitTests(unittest.TestCase):
    def test_split_of_the_real_samples_is_disjoint_by_request_and_user(self):
        data = load_dataset(REAL_DATASET)
        sha = canonical_content_sha256(REAL_DATASET / "sample_requests.csv")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        split = ensure_split([r.request_id for r in data.sample_requests], sha,
                             Path(tmp.name) / "m.json")

        self.assertEqual(len(split.dev) + len(split.report), 25)
        self.assertEqual(set(split.dev) & set(split.report), set())

        by_request = {r.request_id: r.user_id for r in data.sample_requests}
        dev_users = {by_request[r] for r in split.dev}
        report_users = {by_request[r] for r in split.report}
        self.assertEqual(dev_users & report_users, set())

    def test_no_evaluation_request_can_enter_the_split(self):
        data = load_dataset(REAL_DATASET)
        sha = canonical_content_sha256(REAL_DATASET / "sample_requests.csv")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        split = ensure_split([r.request_id for r in data.sample_requests], sha,
                             Path(tmp.name) / "m.json")
        evaluation_ids = {r.request_id for r in data.requests}
        self.assertEqual(set(split.dev + split.report) & evaluation_ids, set())

    def test_frozen_manifest_verifies_against_the_real_sample_file(self):
        """The shipped, migrated `split_manifest.json` must still verify
        against the real `sample_requests.csv` on this machine."""
        data = load_dataset(REAL_DATASET)
        split = ensure_split(
            [r.request_id for r in data.sample_requests],
            canonical_content_sha256(REAL_DATASET / "sample_requests.csv"),
            sample_sha256_raw=file_sha256(REAL_DATASET / "sample_requests.csv"),
            allow_create=False,
        )
        self.assertEqual(split.version, 2)


class PortabilityTests(unittest.TestCase):
    """SPLIT_VERSION 2: the gate is the canonical (newline-normalized)
    content hash, not the raw byte hash, so a CRLF checkout of the same
    content still verifies -- but an actual value change is still caught."""

    def path(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def write_sample(self, tmp: Path, name: str, newline: bytes) -> Path:
        path = tmp / name
        lines = [b"request_id,amount", b"request_01,100", b"request_02,200"]
        path.write_bytes(newline.join(lines) + newline)
        return path

    def test_lf_and_crlf_checkouts_of_identical_content_verify_as_the_same_split(self):
        tmp = self.path()
        lf_path = self.write_sample(tmp, "lf.csv", b"\n")
        crlf_path = self.write_sample(tmp, "crlf.csv", b"\r\n")
        self.assertNotEqual(file_sha256(lf_path), file_sha256(crlf_path))
        self.assertEqual(canonical_content_sha256(lf_path), canonical_content_sha256(crlf_path))

        manifest_path = tmp / "m.json"
        first = ensure_split(IDS, canonical_content_sha256(lf_path), manifest_path,
                             sample_sha256_raw=file_sha256(lf_path))
        second = ensure_split(IDS, canonical_content_sha256(crlf_path), manifest_path,
                              sample_sha256_raw=file_sha256(crlf_path))
        self.assertEqual(first.dev, second.dev)
        self.assertEqual(first.report, second.report)

    def test_an_actual_content_change_is_still_rejected(self):
        tmp = self.path()
        path = tmp / "sample_requests.csv"
        path.write_bytes(b"request_id,amount\nrequest_01,100\n")
        manifest_path = tmp / "m.json"
        ensure_split(IDS, canonical_content_sha256(path), manifest_path)

        path.write_bytes(b"request_id,amount\nrequest_01,999\n")
        with self.assertRaises(SplitError) as ctx:
            ensure_split(IDS, canonical_content_sha256(path), manifest_path)
        self.assertIn("canonical content hash differs", str(ctx.exception))

    def test_version_1_manifest_is_rejected_with_a_migration_message(self):
        tmp = self.path()
        legacy = {
            "version": 1, "salt": "buy-or-wait-2026-09",
            "algorithm": "sha256(salt:request_id) ascending",
            "sample_requests_sha256": "0" * 64,
            "dev": list(IDS[:DEV_SIZE]), "report": list(IDS[DEV_SIZE:]),
        }
        path = tmp / "m.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        with self.assertRaises(SplitError) as ctx:
            load_manifest(path)
        self.assertIn("SPLIT_VERSION 1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
