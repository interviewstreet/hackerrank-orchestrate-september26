"""Global project configuration, paths, usage tracking, and Gemini client initialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai

# Standard repository paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
DATASET_DIR = PROJECT_ROOT / "dataset"
MEDIA_DIR = DATASET_DIR / "media" / "images"
OUTPUT_PATH = DATASET_DIR / "output.csv"
EXCHANGE_RATES_PATH = DATASET_DIR / "exchange_rates.csv"
EXTRACTION_CACHE_DIR = CODE_DIR / "extraction_cache"
USAGE_REPORT_PATH = CODE_DIR / "usage_report.md"

DOTENV_PATH = PROJECT_ROOT / ".env"
if DOTENV_PATH.exists():
    load_dotenv(dotenv_path=DOTENV_PATH)


@dataclass
class UsageTracker:
    model_name: str = "gemini-2.5-flash"
    calls: int = 0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0

    cost_per_1m_input: float = 0.10
    cost_per_1m_output: float = 0.40

    def record_usage(self, response: Any) -> None:
        self.calls += 1
        meta = getattr(response, "usage_metadata", None)
        if meta:
            p_tok = getattr(meta, "prompt_token_count", 0) or 0
            c_tok = getattr(meta, "candidates_token_count", 0) or 0
            t_tok = getattr(meta, "total_token_count", 0) or (p_tok + c_tok)
            self.prompt_tokens += p_tok
            self.candidates_tokens += c_tok
            self.total_tokens += t_tok

    @property
    def estimated_cost_usd(self) -> float:
        input_cost = (self.prompt_tokens / 1_000_000) * self.cost_per_1m_input
        output_cost = (self.candidates_tokens / 1_000_000) * self.cost_per_1m_output
        return input_cost + output_cost

    def generate_report_markdown(self, total_requests: int = 250) -> str:
        cost = self.estimated_cost_usd
        avg_tokens = self.total_tokens / total_requests if total_requests > 0 else 0.0
        avg_cost = cost / total_requests if total_requests > 0 else 0.0

        return f"""# Usage Report: Buy or Wait? Financial Decision Agent

## Model Configuration
- **Model Provider**: Google Gemini
- **Model Name**: {self.model_name}
- **SDK**: `google-genai` (Official Google GenAI Python SDK)

## Extraction Call Summary
- **Total Model Calls**: {self.calls}
- **Input (Prompt) Tokens**: {self.prompt_tokens:,}
- **Output (Candidates) Tokens**: {self.candidates_tokens:,}
- **Total Tokens**: {self.total_tokens:,}
- **Average Tokens per Request** ({total_requests} requests): {avg_tokens:.1f}

## Cost Breakdown
- **Estimated Total Cost (USD)**: ${cost:.4f}
- **Estimated Cost per Request (USD)**: ${avg_cost:.6f}

## Security & Architecture Notes
- LLM is used exclusively for extracting structured evidence from untrusted messages and images.
- Python strictly performs all financial balance calculations, 90-day cash flow projections, and plan rankings deterministically.
- No API keys or credentials are included in this report.
"""


GLOBAL_USAGE = UsageTracker()


def get_model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_genai_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file")
    client = genai.Client(api_key=api_key)
    GLOBAL_USAGE.model_name = get_model_name()
    return client
