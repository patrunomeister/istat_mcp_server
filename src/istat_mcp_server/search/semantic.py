"""Semantic search for ISTAT dataflows.

Embedding backends (in order of preference):
1. Ollama  — uses nomic-embed-text via local HTTP API, no extra Python deps
2. sentence-transformers — fallback if Ollama is not reachable
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..api.models import DataflowInfo

logger = logging.getLogger(__name__)

EMBEDDINGS_CACHE_KEY = 'embeddings:dataflows:v1'

# Ollama settings
OLLAMA_BASE_URL = 'http://localhost:11434'
OLLAMA_MODEL = 'nomic-embed-text'

# sentence-transformers fallback
ST_MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'
_st_model_instance: Any = None


def _build_dataflow_text(df: DataflowInfo) -> str:
    """Concatenate all searchable fields of a dataflow into a single string."""
    parts = [df.id, df.name_it, df.name_en, df.description_it, df.description_en]
    return ' '.join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Return True if Ollama is reachable on localhost."""
    import httpx
    try:
        r = httpx.get(f'{OLLAMA_BASE_URL}/api/tags', timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_embed(texts: list[str]) -> list[list[float]]:
    """Call Ollama /api/embed and return list of embedding vectors."""
    import httpx
    response = httpx.post(
        f'{OLLAMA_BASE_URL}/api/embed',
        json={'model': OLLAMA_MODEL, 'input': texts},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()['embeddings']


# ---------------------------------------------------------------------------
# sentence-transformers fallback
# ---------------------------------------------------------------------------

def _st_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def _st_get_model() -> Any:
    global _st_model_instance
    if _st_model_instance is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f'Loading SentenceTransformer model: {ST_MODEL_NAME}')
        _st_model_instance = SentenceTransformer(ST_MODEL_NAME)
    return _st_model_instance


def _st_embed(texts: list[str]) -> list[list[float]]:
    model = _st_get_model()
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return vectors.tolist()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return True if at least one embedding backend is available."""
    return _ollama_available() or _st_available()


def semantic_search(
    query: str,
    dataflows: list[DataflowInfo],
    cached_embeddings: Any,
    max_results: int = 10,
) -> tuple[list[DataflowInfo], Any]:
    """Search dataflows by semantic similarity.

    Args:
        query: Free-text query (can be multilingual)
        dataflows: Full list of DataflowInfo objects
        cached_embeddings: Previously computed embeddings (list[list[float]]), or None
        max_results: Maximum number of results to return

    Returns:
        Tuple of (matched dataflows, embeddings for caching)
    """
    import numpy as np

    # Choose backend
    use_ollama = _ollama_available()
    backend = 'ollama' if use_ollama else 'sentence-transformers'
    embed_fn = _ollama_embed if use_ollama else _st_embed

    texts = [_build_dataflow_text(df) for df in dataflows]

    if cached_embeddings is None:
        logger.info(f'Computing dataflow embeddings via {backend} (first run, will be cached)')
        corpus_vecs = embed_fn(texts)
    else:
        corpus_vecs = cached_embeddings
        logger.info(f'Using cached dataflow embeddings (backend: {backend})')

    query_vec = embed_fn([query])[0]

    corpus = np.array(corpus_vecs, dtype=float)
    q = np.array(query_vec, dtype=float)

    # Cosine similarity
    norms_c = np.linalg.norm(corpus, axis=1, keepdims=True)
    norm_q = np.linalg.norm(q)
    scores = (corpus / norms_c) @ (q / norm_q)

    top_indices = np.argsort(scores)[::-1][:max_results]
    results = [dataflows[i] for i in top_indices if scores[i] > 0.1]

    logger.info(
        f'Semantic search [{backend}]: query="{query}" → {len(results)} results '
        f'(top score={float(scores[top_indices[0]]):.3f})'
    )

    return results, corpus_vecs
