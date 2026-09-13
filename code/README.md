# Buy or Wait? agent

## Run

From the repository root, run:

```bash
python3 code/main.py
python3 code/evaluation/main.py --samples
```

The first command reads every participant-facing CSV in `dataset/` and writes
the completed `output.csv` in the repository root. The second command compares
the generic agent against public solved samples and validates the generated
submission schema.

## Approach

The agent reconstructs a cash-only financial state from profiles, events,
messages, local evidence images, and dated FX rates. It reserves pending debits,
excludes pending credits and unrealized investments, projects supported
recurrences for 90 days, and tests payment plans day by day against the minimum
balance. It ranks eligible provider options by deadline, spending changes,
cost, start date, payment count, and option ID.

No API key, network request, organizer-only file, or request-specific label is
used. Image OCR is attempted with the locally installed `tesseract` executable
only for events whose CSV amount is blank; a missing unreadable amount is never
silently converted to zero.
