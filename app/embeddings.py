"""Embeddings: Voyage (contracts: voyage-4, 1024 dims, cosine), with an offline hash fallback.

The hash fallback is NOT semantic. It exists so tests and local dev run without a key.
Store `embed_model` on every embedded document.
"""
import hashlib
import math
import re

from .config import get_settings


def model_name() -> str:
    s = get_settings()
    return s.voyage_model if s.embedding_provider == "voyage" else f"hash-{s.embedding_dim}"


def _hash_embed(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for tok in re.findall(r"[a-z0-9_]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """input_type: 'document' when storing, 'query' when searching."""
    s = get_settings()
    if s.embedding_provider == "hash":
        return [_hash_embed(t, s.embedding_dim) for t in texts]
    import voyageai

    client = voyageai.Client(api_key=s.voyage_api_key or None)
    result = client.embed(
        texts, model=s.voyage_model, input_type=input_type, output_dimension=s.embedding_dim
    )
    return result.embeddings


def embed_one(text: str, input_type: str = "document") -> list[float]:
    return embed([text], input_type)[0]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
