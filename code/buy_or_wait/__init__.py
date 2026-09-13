"""Typed, deterministic input foundation for the Buy or Wait challenge."""

from .load import DatasetLoader, DatasetValidationError, LoadedDataset

__all__ = ["DatasetLoader", "DatasetValidationError", "LoadedDataset"]
