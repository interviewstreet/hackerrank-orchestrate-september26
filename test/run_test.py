"""Ad-hoc runner: executes the real pipeline for the 25 requests in
test/test_requests.csv (input columns mirrored from dataset/sample_requests.csv,
see build_test_requests.py) against the real dataset/ context (profiles,
events, rates, messages, images, payment options), so the results can be
diffed against the known-good sample_requests.csv answers via
compare_to_sample.py.

Writes test/test_output.csv. Does not touch dataset/ or the real
output.csv / usage_report.md.

Usage:
    python test/run_test.py
"""
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from fx import FxConverter  # noqa: E402
from loaders import load_dataset, load_requests  # noqa: E402
from output_writer import OUTPUT_COLUMNS, build_output_row, _fallback_result  # noqa: E402
from llm_extract import extract_facts_for_user  # noqa: E402
from event_normalizer import normalize_events  # noqa: E402
from forecast_engine import build_forecast  # noqa: E402
from plan_selector import select_plan  # noqa: E402
from llm_explain import explain_decision  # noqa: E402

DATASET_DIR = REPO_ROOT / "dataset"
TEST_REQUESTS_PATH = TEST_DIR / "test_requests.csv"
TEST_OUTPUT_PATH = TEST_DIR / "test_output.csv"


def main() -> int:
    ds = load_dataset(DATASET_DIR)
    fx = FxConverter(ds.rates_by_pair)

    # load_requests() reads "<dir>/requests.csv" — point it at a scratch dir
    # containing only our test file under that name.
    scratch_dir = TEST_DIR / ".tmp_dataset"
    scratch_dir.mkdir(exist_ok=True)
    (scratch_dir / "requests.csv").write_bytes(TEST_REQUESTS_PATH.read_bytes())
    test_requests = load_requests(scratch_dir)

    rows = []
    extract_usage = []
    explain_usage = []

    for request_id, request in test_requests.items():
        profile = ds.profiles_by_user.get(request.user_id)
        if profile is None:
            rows.append(build_output_row(request_id, _fallback_result("No financial profile available for this user.")))
            continue

        user_events = ds.events_by_user.get(request.user_id, [])
        user_messages = ds.messages_by_user.get(request.user_id, [])
        user_images = ds.images_by_request.get(request_id, [])

        facts, usage = extract_facts_for_user(
            request.user_id, profile.home_currency, user_events, user_messages, user_images, DATASET_DIR
        )
        if usage is not None:
            extract_usage.append(usage)

        clean_timeline = normalize_events(user_events, facts=facts)
        forecast = build_forecast(request.user_id, request.request_date, clean_timeline, profile, fx)
        payment_options = ds.payment_options_by_request.get(request_id, [])
        result = select_plan(request, forecast, profile, payment_options, fx)

        explanation, explain_usage_record = explain_decision(request, profile, result)
        if explain_usage_record is not None:
            explain_usage.append(explain_usage_record)
        result.decision_explanation = explanation

        rows.append(build_output_row(request_id, result))

    with TEST_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    total_calls = len(extract_usage) + len(explain_usage)
    total_in = sum(u.input_tokens for u in extract_usage) + sum(u.input_tokens for u in explain_usage)
    total_out = sum(u.output_tokens for u in extract_usage) + sum(u.output_tokens for u in explain_usage)
    print(f"Wrote {len(rows)} rows to {TEST_OUTPUT_PATH}")
    print(
        f"LLM usage: {total_calls} calls ({len(extract_usage)} llm_extract + {len(explain_usage)} llm_explain), "
        f"{total_in} input / {total_out} output tokens"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
