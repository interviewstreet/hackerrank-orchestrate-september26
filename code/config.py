"""
config.py — Application configuration via Pydantic BaseSettings.

All secrets and tunables are read from environment variables or a .env file.
The only mandatory secret is GEMINI_API_KEY. All other settings have safe defaults.

See .env.example for documentation of every supported variable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Reads from environment variables and/or a .env file (via python-dotenv).
    Fails fast with a clear error if GEMINI_API_KEY is missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Required secret ─────────────────────────────────────────────────────
    gemini_api_key: str = Field(
        description="Google Gemini API key. REQUIRED. Never commit this value.",
    )

    # ── Model configuration ─────────────────────────────────────────────────
    model_name: str = Field(
        default="gemini/gemini-1.5-flash",
        description="LiteLLM model identifier. Format: 'provider/model-name'.",
    )

    model_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM temperature for all structured-extraction calls.",
    )

    # ── Dataset paths ────────────────────────────────────────────────────────
    dataset_dir: Path = Field(
        default=Path("dataset"),
        description="Path to the dataset directory (relative to working dir or absolute).",
    )

    output_path: Path = Field(
        default=Path("dataset/output.csv"),
        description="Path to write the final output.csv.",
    )

    # ── OCR cache ────────────────────────────────────────────────────────────
    ocr_cache_path: Path = Field(
        default=Path("code/evidence/ocr_cache.json"),
        description="Path to the persistent OCR result cache.",
    )

    # ── Concurrency ───────────────────────────────────────────────────────────
    max_workers: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Number of parallel workers for async request evaluation.",
    )

    # ── Reproducibility ───────────────────────────────────────────────────────
    random_seed: int = Field(
        default=42,
        description="Fixed seed for any probabilistic component.",
    )

    # ── Observability ─────────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("dataset_dir", "output_path", "ocr_cache_path", mode="before")
    @classmethod
    def to_path(cls, v: object) -> Path:
        return Path(str(v))

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: object) -> str:
        level = str(v).upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"Invalid log_level: {v}")
        return level


# Singleton — import this wherever settings are needed.
settings = Settings()  # type: ignore[call-arg]
