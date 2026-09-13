"""Buy or Wait? -- deterministic financial decision engine.

Module map (see docs/architecture.md once M4 lands):

    money.py       Decimal parsing, rounding policy, dataset rendering convention
    schema.py      output contract, closed input vocabularies, typed records
    data.py        strict loaders, indexes, request scoping, input hashing
    audit.py       cross-row structural and referential dataset audit
    state.py       cash-state reconstruction from settled/pending/scheduled events
    recurrence.py  recurring commitment/income detection from settled history
    forecast.py    90-day balance forecast and certifiability
    planner.py     payment candidate generation and ranking
    validation.py  the final publishability gate (C0-C17, E1-E7, replay checks)
    output.py      explanation rendering and atomic CSV publication
    evidence.py    request-scoped retrieval, fact validation, conflict resolution
    model.py       bounded, cached, optional provider access (M2)
    assist.py      wires evidence.py/model.py around the deterministic core

Everything except `model.py` is provider- and network-free by construction,
and is fully covered by offline tests. `model.py` is the sole exception, and
only when a caller explicitly constructs and calls a real provider with
credentials the participant supplied -- importing this package, running
`--mode deterministic`, and the full test suite never do.
"""
