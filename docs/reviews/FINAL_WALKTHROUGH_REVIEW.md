# Final Block 1 walkthrough review

Codex CLI, 2026-09-13 ~15:05 IST. E5b is now complete: `validation.py` compares cited-event ownership against both request and profile, and its regression test exists. The 294/295-test, audit and candidate claims are consistent with the intended validation-only change. No paid calls were made.

## Release blocker: stale archive verification metadata

The current `code.zip` hash is `eb63d7bd80b41ee277e463670987ab462c49edb8a52d19d72645f54096ce8531` (49 files). `docs/reviews/FINAL_ARCHIVE_VERIFICATION.json` still records archive hash `53f33f9ddf5abb331ceae153c7a963133eabf6ca7c210c739144d3d370e4c492`, the previous archive. `docs/reviews/FINAL_HANDOFF.md` also still states 48 files and 254 tests. This means the walkthrough's code.zip/metadata claim is not yet a single reproducible release bundle, even though output/trace/usage hashes remain consistent with the frozen assisted run.

Required action before submission: rerun `py -3.12 -B docs/reviews/verify_submission_archive.py` against the current archive (or the approved equivalent), update the verification JSON and handoff with the new archive hash/file count and actual extracted-suite result, then inspect the generated report. Do not manually edit a hash. Reconfirm the archive contains the E5b code/tests and root `evaluation/usage_report.md`, and that `output.csv`, final trace and usage hashes remain the intended predecessor values.

## Release decision

Do not start Block 2. After the verification metadata is regenerated, the safety-hardened Block 1 candidate is suitable for submission with the stated limitations: no accuracy gain demonstrated, message-only changes and recurrence drift unaddressed, E5e deferred, two degraded rows, and mutation effects disabled. The deterministic candidate differs from the assisted submission on six model-fact rows; that is expected and the assisted output remains the chosen artifact.

The transcript must be exported from the participant's actual assistant sessions and redacted. `log.txt` is an internal audit log, not a substitute for the required chat transcript.
