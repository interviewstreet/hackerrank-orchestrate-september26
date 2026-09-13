# Buy or Wait? -- solution

Deterministic financial decision engine with an optional, bounded evidence
layer. See `../AGENTS.md` and `../problem_statement.md` for the challenge
contract; this file only covers setup and how to run this solution.

## Requirements

To use the submitted archive, extract `code.zip` into a directory named `code`
beside the organizer-provided `dataset` directory, then run the commands below
from their shared parent directory. The archive itself starts with `main.py`,
`buy_or_wait/`, and `evaluation/`; it does not contain another `code/` wrapper.

- Python 3.10+ (verified on 3.10.11 and 3.12.5). Standard library only for
  `--mode deterministic` and the audit; `pydantic` is not required.
- `anthropic` (optional) and `ANTHROPIC_API_KEY` (optional) are needed only
  for `--mode assisted` to make real provider calls. Without them, assisted
  mode still runs end to end and falls back to the identical deterministic
  result for every row -- it never crashes or fabricates a fact.

Install the optional provider dependency if you intend to run assisted mode
with real calls:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...   # never hardcode this; read from the environment only
```

On Windows, use `py -3.12 -m pip install anthropic python-dotenv`. If pip is
missing, run `py -3.12 -m ensurepip --upgrade` first. `python-dotenv` is optional
and enables loading a local `.env`; the key must never be submitted.

Alternatively, copy `.env.example` to `.env` at the repo root and set
`ANTHROPIC_API_KEY` there. `python code/main.py` and
`python code/evaluation/main.py` both load `.env` automatically (via the
optional `python-dotenv` package, `pip install python-dotenv`) if it's
present; nothing changes for deterministic mode, and if `python-dotenv`
isn't installed the `.env` file is simply not read and only real environment
variables apply. `.env` is gitignored and must never be committed.

## Run

From the repository root:

```bash
# Validate the dataset only (no predictions written). Exit 0 if clean.
python code/main.py

# Deterministic engine: no model calls, no API key needed.
python code/main.py --mode deterministic --out output.csv

# Assisted: deterministic core plus evidence extraction from messages/images.
# Falls back to the deterministic result per-row on any provider/extraction
# failure, and produces byte-identical output to deterministic mode when no
# provider is configured.
python code/main.py --mode assisted --out output.csv
```

Both prediction modes read only from `dataset/` and refuse to run if the
dataset audit finds a structural error.

## Test

```bash
python -B -m unittest discover -s code/tests -t code -p "test_*.py"
```

All tests are offline: synthetic fixtures, a fake provider, and an injectable
clock. No test requires network access or an API key.

## Evaluate against the public samples

```bash
# Show the frozen development/reporting split.
python code/evaluation/main.py --show-split

# Score a subset. --split dev is for tuning only; --split report is the
# fixed public-sample reporting subset (exposure disclosed, not held-out).
python code/evaluation/main.py --split dev    --mode deterministic
python code/evaluation/main.py --split report --mode assisted --compare-baseline
```

`--compare-baseline` additionally scores the no-model deterministic baseline
on the same request set when `--mode assisted` is selected, so the evidence
layer's effect on each row is visible directly rather than inferred from two
separately run reports.

## Layout

```text
code/
├── main.py                 CLI entry point (audit / deterministic / assisted)
├── buy_or_wait/            the engine -- see buy_or_wait/__init__.py for the module map
├── prompts/                versioned extraction policy used by the evidence layer
├── evaluation/             split manifest, label loader, scoring, usage_report.md
└── tests/                  offline test suite
```

`code/buy_or_wait/model.py` is the only module that imports a provider SDK or
touches the network, and only when a caller explicitly builds
`AnthropicProvider` with a configured key. Every other module -- including
the entire deterministic core -- is provider-free by construction and is
what `--mode deterministic` and the full test suite exercise.

## Recorded submission run

`evaluation/usage_report.md` documents the recorded 250-row assisted run.
`evaluation/final/manifest.json` identifies the matching output by SHA-256,
with trace and usage records alongside it. `evaluation/final/reporting/`
contains a separately measured comparison on the frozen public reporting subset.
These records are audit artifacts; prediction code never reads them as labels.

The evidence layer currently runs only for unknown event amounts. It does not
investigate message-only changes on every request. Two output rows remain
degraded. Passing the internal financial gate is conditional on the forecast;
it is not a guarantee of accuracy against the public examples. The reporting
comparison shows 6/15 status matches and 8/15 method matches for both modes.
