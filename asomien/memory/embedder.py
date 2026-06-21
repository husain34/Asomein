"""
asomien/memory/embedder.py

Embedder class wrapping sentence-transformers for vectorizing memory nodes.
"""

from typing import List
import logging

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger(__name__)

class Embedder:
    """Generates vector embeddings for TRACE-XP memory nodes using sentence-transformers."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Initialize the embedder with the specified small, efficient model."""
        self.model_name = model_name
        self._model = None
        
        if SentenceTransformer is None:
            logger.warning("[Embedder] sentence-transformers is not installed. Embeddings will not be generated.")
        else:
            try:
                # Lazy loading of the model to save memory until first use
                logger.info("[Embedder] Initializing model %s (lazy load will happen on first encode).", model_name)
            except Exception as e:
                logger.error("[Embedder] Failed to initialize Embedder: %s", e)

    def _get_model(self):
        if self._model is None and SentenceTransformer is not None:
            logger.info("[Embedder] Loading SentenceTransformer model %s...", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for a list of text strings."""
        model = self._get_model()
        if model is None:
            logger.warning("[Embedder] Model unavailable; returning empty embeddings.")
            return [[] for _ in texts]
            
        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            logger.error("[Embedder] Error generating embeddings: %s", e)
            return [[] for _ in texts]

    def get_embedding(self, text: str) -> List[float]:
        """Generate a vector embedding for a single text string."""
        results = self.encode([text])
        return results[0] if results else []
