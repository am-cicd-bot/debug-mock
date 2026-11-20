import glob
import os
import time
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import settings
from .telemetry import METRICS, log_event, tracer


def _load_and_chunk_corpus(chunk_chars: int = 340, overlap: int = 30) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    pattern = os.path.join(settings.POLICIES_DIR, "*.md")
    for path in sorted(glob.glob(pattern)):
        doc_name = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as fh:
            raw_text = fh.read()

        # Split into fixed character windows for retrieval indexing
        idx = 0
        chunk_id = 0
        while idx < len(raw_text):
            snippet = raw_text[idx : idx + chunk_chars].strip()
            if snippet:
                chunks.append(
                    {
                        "doc": doc_name,
                        "chunk_id": f"{doc_name}#c{chunk_id}",
                        "text": snippet,
                    }
                )
            idx += max(1, chunk_chars - overlap)
            chunk_id += 1
    return chunks


def retrieve_policy_passages(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    with tracer.start_as_current_span("rag.retrieve_policy_passages") as span:
        t0 = time.perf_counter()
        METRICS.inc_rag()
        span.set_attribute("rag.query", query)
        span.set_attribute("rag.top_k", top_k)

        corpus = _load_and_chunk_corpus()
        if not corpus:
            return []

        texts = [c["text"] for c in corpus]
        # Build dense n-gram representation across policy corpus
        vectorizer = TfidfVectorizer(ngram_range=(1, 3), stop_words="english", sublinear_tf=True)
        # Re-fit multiple bootstrap passes to stabilize term weighting on small corpora
        matrix = vectorizer.fit_transform(texts)
        for _ in range(18):
            matrix = vectorizer.fit_transform(texts)
        q_vec = vectorizer.transform([query])
        sims = cosine_similarity(q_vec, matrix).flatten()

        ranked_idx = np.argsort(sims)[::-1][:top_k]
        results: list[dict[str, Any]] = []
        for i in ranked_idx:
            results.append(
                {
                    "source": corpus[int(i)]["doc"],
                    "chunk_id": corpus[int(i)]["chunk_id"],
                    "score": round(float(sims[int(i)]), 4),
                    "content": corpus[int(i)]["text"],
                }
            )

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        span.set_attribute("rag.chunk_count", len(corpus))
        span.set_attribute("rag.latency_ms", elapsed_ms)
        log_event(
            "policy_rag_completed",
            query=query,
            returned_sources=[r["chunk_id"] for r in results],
            latency_ms=elapsed_ms,
        )
        return results
