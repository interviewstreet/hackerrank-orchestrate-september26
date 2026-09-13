# M0 implementation review

Date: 2026-09-12. Reviewer: Codex CLI. Scope: Claude's M0 implementation in `code/buy_or_wait/`, `code/evaluation/`, tests, and the M0 handoff. Verdict: **fix-first before M1**.

## What passed

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"` passes: 77 tests.
- `py -3.12 -B code/main.py` audits the real dataset with 0 findings and 0 errors.
- `code/main.py --mode deterministic` exits 2 and writes no prediction file, so it does not mislabel placeholders as a baseline.
- `code/evaluation/main.py --show-split` prints the frozen `ecafb49177d9` manifest with 10 development and 15 reporting rows, disjointness, and exposure disclosure.
- `RequestInput` has no expected-output fields, and the engine package does not import the evaluator.
- Decimal parsing, blank-as-unknown handling, exact directed FX presence on the current dataset, link-cycle checks, option arithmetic, and input CSV hashes are covered by the existing suite.

These results validate M0's documented scope. They do not validate a financial forecast: M1 is not implemented, no output predictions exist, and the usage report is correctly still empty until a real final run.

## Findings

### R-M0-01 — P1: CSV row-width corruption is accepted

`code/buy_or_wait/data.py:189-207` uses `csv.DictReader` and checks only the header. `DictReader` silently stores an extra cell under a `None` key and fills a missing trailing cell with `None`; the loaders then call `row[column]` for expected columns and can accept both cases. The cross-row audit also does not inspect row width.

Reproduction: append `UNEXPECTED_CELL` to one financial-events row; `load_dataset()` and `audit_dataset()` both succeed. Remove the final `message_text` cell from a message; it also succeeds with an empty message.

Impact: malformed or shifted financial data can reach M1 while its file hash and “0 findings” status suggest a valid dataset. A missing amount or message can change affordability/evidence decisions.

Correction: in `read_rows`, reject `reader` rows with `None` keys or missing values before typed parsing, with source/row diagnostics. Add extra-cell and truncated-row fixtures to `test_data.py`.

### R-M0-02 — P1: Image IDs can escape the media directory

`code/buy_or_wait/audit.py:126-151` constructs `media_dir / image.filename()` where `filename()` returns the untrusted `image_id + ".png"`. There is no filename/path-component validation or resolved-path containment check.

Reproduction: set an image ID to `../../../outside`; create that file outside `dataset/media/images`; the audit accepts it and the resolved path escapes the supplied media directory.

Impact: a malformed participant input can make later vision code read arbitrary files, violating the dataset-only contract. The current dataset uses safe IDs, but this is a loader boundary that should fail closed.

Correction: require an image ID to be a safe single filename component (for example, a strict identifier pattern) and verify `resolve().parent == media_dir.resolve()` before existence checks. The model layer must use the same safe resolver. Add traversal and absolute-path fixtures.

### R-M0-03 — P1: Cross-user request references are not audited

`code/buy_or_wait/audit.py:178-190` checks that a message's `request_id` exists, but not that the referenced request belongs to `message.user_id`. `DataSet.request_context()` then filters messages by the active user's index and includes the message when the ID matches the request, regardless of ownership.

Reproduction: make a `user_01` message reference `sample_01`, which belongs to `user_02`; the clean fixture still audits with no errors, and the reference can be included when evaluating the corresponding request ID.

Impact: request-scoped evidence can cross users. This directly undermines the evidence-audit requirement and can expose another user's request context to extraction/planning.

Correction: index request owners and reject any message/image whose nonblank `request_id` has a different owner. In `request_context`, assert the same invariant rather than relying only on filtering. Add cross-user message and image tests.

### R-M0-04 — P2: Monetary parsing rounds FX rates and source values at load time

`code/buy_or_wait/money.py:58-61` quantizes every parsed amount to `0.01`; `load_exchange_rates()` calls that path. A supplied rate of `20.12345` becomes `20.12` without warning. The current data happens to have two-decimal rates, so the real audit does not expose it.

Reproduction: a temporary rate row with `20.12345` loads as `Decimal("20.12")` and produces no finding.

Impact: future or changed supplied rates are altered before conversion. This can move a payment across the minimum-balance boundary and violates “use the supplied fixed rate.” Event/payment amounts may use a rendering precision policy, but rates should retain source precision until the final home-currency amount is explicitly rounded.

Correction: separate `parse_decimal` from output-money quantization. Preserve rates at source precision; apply an explicit, documented rounding operation only to converted monetary values and output fields. Add a high-precision rate test.

### R-M0-05 — P2: The input manifest does not cover image bytes

`code/buy_or_wait/data.py:574-578` hashes only the CSV files listed in `EXPECTED_HEADERS`. `images.csv` is hashed, but the 16 PNG contents are not. Changing an image in place leaves `DataSet.manifest` unchanged.

Reproduction: mutate `dataset/media/images/image_01.png`; two loads return identical manifests.

Impact: M2 content-hash caches and final-run provenance cannot detect changed evidence bytes. A final usage/output report could be associated with different image content than the run that was measured.

Correction: include a deterministic manifest entry for every supplied media file (relative path plus SHA-256), or have the model cache record and verify those hashes. Keep media metadata and content hashes distinct and test changed bytes.

### R-M0-06 — P2: Date parser accepts non-contract ISO forms

`code/buy_or_wait/data.py:114-127` uses `date.fromisoformat`, which accepts compact `20240303` and ISO week dates such as `2024-W09-7`, despite the contract requiring `YYYY-MM-DD`.

Reproduction: both values parse as `2024-03-03`.

Impact: input normalization can silently reinterpret malformed dates, affecting request deadlines, settlement dates, recurrence, and forecast boundaries.

Correction: validate the exact `^\d{4}-\d{2}-\d{2}$` shape before `date.fromisoformat()`. Add compact/week-date rejection tests.

### R-M0-07 — P2: Loader accepts a forged request object without ownership validation

`DataSet.request_context()` looks up the profile by `request.user_id` and options by `request.request_id`, but does not verify that this `(request_id, user_id)` pair exists in the loaded request set. A caller can combine a known request ID with another known user's ID and receive that user's profile/events while retaining the first request's payment options.

Reproduction: replace `request_01.user_id` with `user_02`; `request_context()` returns user 02's profile and request 01's options.

Impact: an integration bug or untrusted model-produced request object could create a mixed-user financial state. M1 should not have to trust callers to preserve the pair.

Correction: index immutable request ownership and require an exact request record match (or make `request_context` accept only a request object retrieved from the dataset). Add a forged-pair test.

### R-M0-08 — P2: The M0 suite does not test the contract boundary it claims to protect

The 77 tests cover headers, IDs, labels, and selected references, but no test fails on extra/missing CSV cells, image traversal, cross-user request references, media-content manifest changes, strict calendar formatting, or forged request/user pairs. An independent seven-probe suite reproduced all of these gaps; all seven fail against the current implementation.

Correction: add the regression cases above to the normal offline suite after fixing them. Keep them as negative fixtures that independently assert the loader/audit rejects the defect, rather than weakening the probes.

## Non-findings and limits

- Exact FX lookup is correct for the current data: all 140 foreign events have an exact directed settlement-date rate. The plan must still preserve exactness if the dataset changes.
- Split creation and verification are deterministic and refuse silent regeneration. Hashing the sample CSV also detects user/label changes in that file.
- The local `.claude/settings.local.json` configuration remains unchanged; the shared `Edit(/dataset/**)` rule is present. This is a Claude file-tool guard, not a sandbox for arbitrary subprocesses.
- No M1 forecast, recurrence, plan, atomic writer, model layer, retry budget, or usage report exists yet, so those areas are not passed by this review.
- The seven regression probes were run against temporary copies only. They did not mutate the repository dataset or application files.

## Required disposition

Fix R-M0-01 through R-M0-03 before M1 because they can corrupt or cross-scope input data. Fix R-M0-04 through R-M0-07 in the same M0 cleanup because the corrections are small and directly affect the M1 interfaces. Add the tests before declaring M0 closed. Then rerun the original 77 tests plus the new regressions and update `docs/IMPLEMENTATION_STATUS.md` with real counts.

Do not begin paid extraction while these boundary defects remain. Once M0 is corrected, M1 can proceed with the deterministic financial core under the already-agreed workflow.

VERDICT: fix-first
