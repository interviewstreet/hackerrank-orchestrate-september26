"""Configuration for the Buy or Wait? agent.

All paths resolve from this file's location so the agent runs from any CWD.
Secrets come from the environment only -- never hardcoded, never logged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# code/config.py -> code/ -> repo root
CODE_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = CODE_DIR.parent


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = Field(..., description="Groq API key, from env or .env")

    # ---- Models ------------------------------------------------------------
    # qwen3.8-27b is primary: vision + tool calling at ~30-66 output tokens.
    # qwen3.6-27b is avoided -- hard OTPM cap of 1000 rejects max_tokens>1000
    # and it spends ~150 tokens per call on reasoning traces.
    orchestrator_model: str = "qwen/qwen3.8-27b"
    # Rate limits are per model, so each job gets its own bucket rather than
    # sharing one. gpt-oss-20b is deliberately kept OUT of this pool: it runs
    # the message resolver, whose 2000-token ceiling makes each of its calls
    # expensive against TPM, and stacking orchestrator turns on the same bucket
    # was measurably provoking 429s. Both pool models were verified to support
    # multi-turn tool calling.
    orchestrator_pool: tuple[str, ...] = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b")
    vision_model: str = "qwen/qwen3.8-27b"
    resolver_model: str = "openai/gpt-oss-20b"
    escalation_model: str = "openai/gpt-oss-120b"
    safety_model: str = "meta-llama/llama-prompt-guard-2-86m"
    safety_policy_model: str = "openai/gpt-oss-safeguard-20b"

    # ---- Embeddings (local, no API, immune to rate limits) -----------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    similarity_threshold: float = 0.60
    few_shot_k: int = 2

    # ---- Agent loop --------------------------------------------------------
    # A request carrying evidence needs four turns at minimum (context,
    # resolve, forecast + plans, submit), so 6 leaves room for one validator
    # correction without letting the loop wander. Each turn spends a call
    # against a per-model daily quota of ~1000.
    max_iterations: int = 6
    max_retries: int = 2
    temperature: float = 0.0
    max_output_tokens: int = 900
    # The resolver returns a nested list and runs on a reasoning model, so it
    # needs more headroom than a leaf extraction; below this it truncates
    # mid-JSON and the whole answer is lost.
    resolver_max_tokens: int = 2000

    # ---- Rate-limit budget (measured from x-ratelimit headers) -------------
    requests_per_day_per_model: int = 1000
    tokens_per_minute: int = 8000
    budget_warn_fraction: float = 0.75

    # ---- Forecast ----------------------------------------------------------
    forecast_days: int = 90
    min_history_for_recurrence: int = 2

    # ---- Paths -------------------------------------------------------------
    @property
    def dataset_dir(self) -> Path:
        return REPO_ROOT / "dataset"

    @property
    def images_dir(self) -> Path:
        return self.dataset_dir / "media" / "images"

    @property
    def cache_dir(self) -> Path:
        path = CODE_DIR / ".cache"
        path.mkdir(exist_ok=True)
        return path

    @property
    def output_paths(self) -> tuple[Path, ...]:
        """Spec fills dataset/output.csv; submission expects output.csv."""
        return (REPO_ROOT / "output.csv", self.dataset_dir / "output.csv")

    @property
    def usage_report_path(self) -> Path:
        return CODE_DIR / "evaluation" / "usage_report.md"


OUTPUT_COLUMNS: tuple[str, ...] = (
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
)

# Per-million-token USD pricing, for evaluation/usage_report.md.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "qwen/qwen3.8-27b": (0.15, 0.60),
    "qwen/qwen3.6-27b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-safeguard-20b": (0.075, 0.30),
    "meta-llama/llama-prompt-guard-2-86m": (0.03, 0.03),
}


def get_settings() -> Settings:
    """Load settings, raising a clear error when the API key is absent."""
    return Settings()  # type: ignore[call-arg]
