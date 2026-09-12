from code.src.pipeline import FinancialAgentPipeline
from code.src.config import DATASET_DIR


def test_end_to_end_request_01():
    pipeline = FinancialAgentPipeline(DATASET_DIR)
    out = pipeline.process_request("request_01")

    assert out.request_id == "request_01"
    assert out.affordability_status == "affordable_now"
    assert out.recommended_payment_method == "full_payment"
    assert out.payment_plan == "2024-03-03:25256"
    assert out.earliest_date_for_full_payment == "2024-03-03"
    assert out.spending_changes_needed == "none"
    assert "ZAR" in out.decision_explanation

    csv_d = out.to_csv_dict()
    assert len(csv_d) == 8
    assert csv_d["amount_safe_to_pay"] == "25256"
