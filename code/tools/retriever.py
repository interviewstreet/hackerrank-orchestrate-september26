"""Local semantic retrieval over the labelled samples and the event history.

Everything here runs on the CPU with no API key, so it consumes none of the
Groq quota -- the one part of the pipeline immune to rate limits.

Two indexes, each earning its place:

* **samples** -- for an incoming request, find the closest completed example in
  ``sample_requests.csv`` and show the agent how that decision was worded.
  Semantic similarity beats matching on ``request_type``, because "Can I afford
  this laptop?" is nearer to "Should I buy this monitor?" than to a tuition
  question even though both are ``purchase``.
* **events** -- match a provider or employer name in a message to the recurring
  *series* it belongs to. Note that this deliberately does not fabricate a
  ``related_event_id``: messages.csv leaves that blank precisely when no single
  event row corresponds, so the target is the series, not a row.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=2)
def _load_encoder(model_name: str):
    """Load a sentence-transformer once per process.

    Loading costs several seconds and tens of megabytes, so an index created per
    message -- as series matching does -- must not pay for it each time.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


@dataclass
class Hit:
    text: str
    score: float
    payload: dict


class EmbeddingIndex:
    """FAISS inner-product index over normalised sentence embeddings."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None
        self._index = None
        self._texts: list[str] = []
        self._payloads: list[dict] = []

    def _encoder(self):
        # Resolved lazily and shared process-wide: a deterministic-only run
        # never loads the model at all.
        if self._model is None:
            self._model = _load_encoder(self._model_name)
        return self._model

    def build(self, texts: list[str], payloads: list[dict]) -> None:
        if not texts:
            return
        import faiss

        self._texts = texts
        self._payloads = payloads
        vectors = self._encoder().encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        matrix = np.asarray(vectors, dtype="float32")
        self._index = faiss.IndexFlatIP(matrix.shape[1])
        self._index.add(matrix)

    def search(self, query: str, top_k: int = 3, threshold: float = 0.0) -> list[Hit]:
        if self._index is None or not query.strip():
            return []
        vector = self._encoder().encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        )
        scores, indices = self._index.search(np.asarray(vector, dtype="float32"), top_k)
        hits: list[Hit] = []
        for score, position in zip(scores[0], indices[0]):
            if position < 0 or float(score) < threshold:
                continue
            hits.append(
                Hit(
                    text=self._texts[position],
                    score=float(score),
                    payload=self._payloads[position],
                )
            )
        return hits


class SampleRetriever:
    """Few-shot retrieval over the completed sample requests."""

    def __init__(self, model_name: str, samples: list[dict]) -> None:
        self.index = EmbeddingIndex(model_name)
        payloads = [
            {
                "request_id": row["request_id"],
                "request_type": row["request_type"],
                "affordability_status": row["affordability_status"],
                "recommended_payment_method": row["recommended_payment_method"],
                "payment_plan": row["payment_plan"],
                "spending_changes_needed": row["spending_changes_needed"],
                "decision_explanation": row["decision_explanation"],
            }
            for row in samples
        ]
        texts = [
            f"{row['request_type']}: {row['request_text']}" for row in samples
        ]
        self.index.build(texts, payloads)

    def examples(self, request_type: str, request_text: str, k: int = 2) -> str:
        """Render the nearest completed examples as style guidance."""
        hits = self.index.search(f"{request_type}: {request_text}", top_k=k)
        if not hits:
            return ""
        lines = ["Reference examples of accepted answers for similar requests:"]
        for hit in hits:
            p = hit.payload
            lines.append(
                f"- [{p['request_type']}] status={p['affordability_status']} "
                f"method={p['recommended_payment_method']} "
                f"plan={p['payment_plan']} changes={p['spending_changes_needed']}\n"
                f"  explanation: {p['decision_explanation']}"
            )
        lines.append(
            "Match this explanation style: state the action, the amount, the "
            "date, and the balance that stays protected. Do not copy the "
            "numbers -- they belong to a different user."
        )
        return "\n".join(lines)


class SeriesMatcher:
    """Link a message to the recurring series it most likely describes."""

    def __init__(self, model_name: str, threshold: float = 0.6) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self._signature: tuple[str, ...] | None = None
        self._index: EmbeddingIndex | None = None
        # One matcher is shared by every worker thread, so the cached index has
        # to be swapped under a lock: without it two threads with different
        # series sets would race and one could search the other's index.
        self._lock = threading.Lock()

    def match(self, message_text: str, series: list) -> str | None:
        """Return a series_key when one clearly corresponds, else None."""
        if not series or not message_text.strip():
            return None
        hits = self._index_for(series).search(
            message_text, top_k=1, threshold=self.threshold
        )
        return hits[0].payload["series_key"] if hits else None

    def _index_for(self, series: list) -> EmbeddingIndex:
        """Reuse the index while the series set is unchanged.

        Every message for one person is matched against the same series, so
        rebuilding per message would re-encode identical text repeatedly.
        """
        signature = tuple(s.key for s in series)
        with self._lock:
            if self._index is None or signature != self._signature:
                index = EmbeddingIndex(self.model_name)
                index.build(
                    [
                        f"{s.category} {' '.join(dict.fromkeys(s.descriptions))}"
                        for s in series
                    ],
                    [{"series_key": s.key} for s in series],
                )
                self._index, self._signature = index, signature
            return self._index
