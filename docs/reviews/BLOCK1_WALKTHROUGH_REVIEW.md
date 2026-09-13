# Block 1 walkthrough review

Codex CLI, 2026-09-13 ~14:57 IST. No application edits or paid calls.

## Disposition

The walkthrough is accurate overall. The four E5 checks are placed after literal parsing and before permission checks, and the existing shared decision path is unchanged. E5e is explicitly deferred and documented, which resolves the prior plan ambiguity. Block 2 should remain deferred.

The deterministic candidate differing from the assisted output on six rows is expected and correctly explained; it does not contradict the unchanged assisted `output.csv` claim. A validation-only code change can preserve predictions while still producing a new archive. The final archive verification metadata now reflects the new archive (49 files, SHA256 beginning `53f33f9d`) and output hash `e445b252...`; verify these exact values once more immediately before upload, because generated files are easy to stale.

## R-B1-02 — minor defense-in-depth mismatch

The release plan says E5b compares the cited event owner against both `request.user_id` and `profile.user_id`. Current `validation.py` checks only `cited_event.user_id != request.user_id`. Normal dataset loading ties the request/profile context together, so this is not evidence of a current output error. It is nevertheless a discrepancy between the approved plan and implementation and leaves a malformed caller context less protected.

Minimal action: either add the profile comparison and a regression test for a mismatched profile, or explicitly amend the handoff to say request ownership is the sole checked invariant and defer the belt-and-suspenders check. Given the deadline, adding the one comparison/test is low risk but must be followed by the full suite and candidate hash check. Do not start Block 2 for this.

## Release gate

Before submission, run the 294-test suite on the available supported interpreter, audit mode, deterministic candidate to a temporary path, archive builder, and clean archive verifier. Confirm the candidate is compared to the correct predecessor (assisted output, not deterministic output), and that `FINAL_ARCHIVE_VERIFICATION.json`, final manifest hashes, archive hash, usage report and output all describe the same selected submission. Preserve the prior archive/output until the final candidate passes. Export the actual chat transcript with credentials redacted; local `log.txt` is not a substitute.

No accuracy improvement is demonstrated by this change. The submission should describe Block 1 as validation hardening and retain disclosed limitations: message-only changes, recurrence/calendar drift, internal rounding and provider operational accounting. Do not claim E5e or Block 2 were implemented.
