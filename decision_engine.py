from datetime import date
from typing import List, Optional

from models import CandidatePlan


class DecisionEngine:
    """Rank candidate plans according to the specification.

    Ordering (higher priority first):
    1. Meets deadline (True > False)
    2. No spending changes (False > True)  # uses_spending_changes flag
    3. Lowest total paid
    4. Earliest start date
    5. Fewer payments (payment_count)
    6. Lowest payment_option_id (lexicographically)
    """

    @staticmethod
    def _prepare_plan(plan: CandidatePlan) -> CandidatePlan:
        # Ensure helper fields exist; they may be set by the generator.
        return plan

    def rank_candidates(self, candidates: List[CandidatePlan]) -> List[CandidatePlan]:
        for p in candidates:
            self._prepare_plan(p)

        def sort_key(p: CandidatePlan):
            return (
                not p.meets_deadline,                     # False (meets) first
                p.uses_spending_changes,                 # False (no changes) first
                p.total_paid,                            # lower first
                p.start_date or date.max,                # earlier first
                p.payment_count,                         # lower first
                p.payment_option_id or "~"              # lexicographically lower first
            )
        return sorted(candidates, key=sort_key)

    def select_best_plan(self, candidates: List[CandidatePlan]) -> Optional[CandidatePlan]:
        ranked = self.rank_candidates(candidates)
        return ranked[0] if ranked else None
