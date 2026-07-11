import os
from sentence_transformers import SentenceTransformer

# Global lazy-loaded embedding model instance
_model = None

def get_embedding_model():
    """Lazily loads the SentenceTransformer embedding model and caches it."""
    global _model
    if _model is None:
        model_name = os.getenv("EMBEDDING_MODEL_NAME", "nomic-ai/nomic-embed-text-v1.5")
        cache_dir = os.getenv("HF_HOME", "./hf_cache")
        print(f"Loading local embedding model: {model_name}...")
        
        # nomic-embed-text-v1.5 requires trust_remote_code=True
        _model = SentenceTransformer(
            model_name, 
            cache_folder=cache_dir,
            trust_remote_code=True
        )
        print("Embedding model loaded successfully.")
    return _model

def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Generates dense embeddings for a list of document chunks.
    For nomic-embed-text-v1.5, documents must be prefixed with 'search_document: '.
    """
    model = get_embedding_model()
    # Format texts with Nomic specific document prefix
    prefixed_texts = [f"search_document: {text}" for text in texts]
    embeddings = model.encode(prefixed_texts, convert_to_numpy=True)
    return embeddings.tolist()

def embed_query(query: str) -> list[float]:
    """
    Generates a dense embedding for a single search query.
    For nomic-embed-text-v1.5, queries must be prefixed with 'search_query: '.
    """
    model = get_embedding_model()
    # Format query with Nomic specific query prefix
    prefixed_query = f"search_query: {query}"
    embedding = model.encode(prefixed_query, convert_to_numpy=True)
    return embedding.tolist()
