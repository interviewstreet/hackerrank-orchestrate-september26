from code.src.models import FinancialEvent


def resolve_event_lifecycle(events: list[FinancialEvent]) -> list[FinancialEvent]:
    """
    Resolves linked_event_id relationships and filters out non-cash,
    cancelled, failed, or superseded events according to challenge rules:
    - Cancelled or failed transactions are excluded.
    - Unrealized non-cash investment valuations are excluded.
    - Pending credits (refunds, bonuses, etc.) are excluded.
    - If a card authorization (cancelled) is linked to a settled charge, authorization is dropped.
    - If a failed payment is linked to a scheduled retry, the retry is kept and failed dropped.
    """
    events_by_id = {e.event_id: e for e in events}
    
    # Identify superseded event IDs
    superseded_ids = set()
    for e in events:
        if e.linked_event_id and e.linked_event_id in events_by_id:
            parent = events_by_id[e.linked_event_id]
            # If parent is cancelled or failed and child is settled or scheduled, drop parent
            if parent.status in ("cancelled", "failed"):
                superseded_ids.add(parent.event_id)
            # If child is cancelled, drop child
            if e.status in ("cancelled", "failed"):
                superseded_ids.add(e.event_id)

    resolved = []
    for e in events:
        # Rule 1: Exclude cancelled or failed
        if e.status in ("cancelled", "failed"):
            continue

        # Rule 2: Exclude unrealized non-cash investment valuations
        if e.status == "unrealized" or e.direction == "non_cash":
            continue

        # Rule 3: Exclude pending credits
        if e.status == "pending" and e.direction == "credit":
            continue

        # Rule 4: Exclude superseded
        if e.event_id in superseded_ids:
            continue

        resolved.append(e)

    return resolved
