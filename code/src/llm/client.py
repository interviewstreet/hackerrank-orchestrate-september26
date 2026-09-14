import os
import threading
from openai import OpenAI
from code.src.config import OPENAI_API_KEY, OPENAI_MODEL


class TokenTracker:
    def __init__(self):
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model_name = OPENAI_MODEL
        self._lock = threading.Lock()
        # Pricing per 1M tokens (gpt-4o-mini default estimates: $0.15/1M input, $0.60/1M output)
        self.input_cost_per_million = 0.15
        self.output_cost_per_million = 0.60

    def record_usage(self, prompt_tokens: int, completion_tokens: int, model: str | None = None):
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            if model:
                self.model_name = model

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost_usd(self) -> float:
        input_cost = (self.prompt_tokens / 1_000_000.0) * self.input_cost_per_million
        output_cost = (self.completion_tokens / 1_000_000.0) * self.output_cost_per_million
        return round(input_cost + output_cost, 6)

    def generate_report_markdown(self, total_requests: int = 250) -> str:
        avg_tokens = self.total_tokens / total_requests if total_requests else 0
        avg_cost = self.estimated_cost_usd / total_requests if total_requests else 0

        return f"""# Token Usage and Cost Analysis Report

HackerRank Orchestrate (September 2026) — Buy or Wait?

- **Provider**: OpenAI
- **Model**: `{self.model_name}`
- **Total Model Calls**: {self.calls}
- **Total Prompt Tokens**: {self.prompt_tokens}
- **Total Completion Tokens**: {self.completion_tokens}
- **Total Tokens**: {self.total_tokens}
- **Total Requests Evaluated**: {total_requests}
- **Average Tokens per Request**: {avg_tokens:.1f}
- **Total Estimated Cost**: ${self.estimated_cost_usd:.4f} USD
- **Average Cost per Request**: ${avg_cost:.6f} USD
"""


# Singleton tracker
global_tracker = TokenTracker()

_client: OpenAI | None = None


def get_openai_client() -> OpenAI | None:
    global _client
    if _client is None:
        api_key = OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        _client = OpenAI(api_key=api_key)
    return _client
