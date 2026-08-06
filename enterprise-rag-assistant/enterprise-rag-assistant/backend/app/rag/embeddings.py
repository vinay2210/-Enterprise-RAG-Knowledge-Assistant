"""
Embedding provider abstraction.

"local" -> sentence-transformers (BGE small), runs on CPU, free, no API key,
           great for a beginner getting this running end-to-end tonight.
"openai" -> text-embedding-3-small via the OpenAI API, higher quality,
           costs money, needs OPENAI_API_KEY.

Both implementations expose the same embed(texts: list[str]) -> list[list[float]]
so the rest of the pipeline never needs to know which one is active.
"""
import hashlib
import math
import re
from functools import lru_cache

from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()


class SimpleEmbedder:
    """Deterministic fallback embedder used when torch/sentence-transformers cannot load."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts: dict[str, int] = {}

        for token in self._tokenize(text):
            counts[token] = counts.get(token, 0) + 1

        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            vector[index] += float(count)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)


class LocalEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading local embedding model '{model_name}' (first run downloads it)...")
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # BGE models recommend a query instruction prefix at query-time only;
        # for indexing we embed raw chunk text.
        vectors = self.model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        instructed = f"Represent this sentence for searching relevant passages: {text}"
        vector = self.model.encode([instructed], normalize_embeddings=True)
        return vector[0].tolist()


class OpenAIEmbedder:
    def __init__(self, model_name: str, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Batch to stay well under request size limits on large documents.
        all_vectors: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = self.client.embeddings.create(model=self.model_name, input=batch)
            all_vectors.extend([d.embedding for d in resp.data])
        return all_vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@lru_cache
def get_embedder():
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY in .env")
        return OpenAIEmbedder("text-embedding-3-small", settings.openai_api_key)
    # Prefer the local embedder, but if loading it fails (e.g. App Control
    # blocked a Torch DLL) try to fall back to OpenAI if the API key is set.
    try:
        return LocalEmbedder(settings.embedding_model)
    except Exception as e:
        logger.warning("Local embedder failed to initialize: %s", e)
        if settings.openai_api_key:
            logger.info("Falling back to OpenAI embedder because OPENAI_API_KEY is set.")
            return OpenAIEmbedder("text-embedding-3-small", settings.openai_api_key)

        logger.info("Falling back to deterministic local embeddings because the torch-based model is unavailable.")
        return SimpleEmbedder()
