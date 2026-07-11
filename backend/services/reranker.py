import os
from sentence_transformers import CrossEncoder

# Global lazy-loaded reranker model instance
_reranker = None

def get_reranker_model():
    """Lazily loads and caches the CrossEncoder reranker model."""
    global _reranker
    if _reranker is None:
        model_name = os.getenv("RERANKER_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        cache_dir = os.getenv("HF_HOME", "./hf_cache")
        print(f"Loading local reranker model: {model_name}...")
        
        # Load cross-encoder model
        _reranker = CrossEncoder(
            model_name,
            cache_folder=cache_dir,
            max_length=512
        )
        print("Reranker model loaded successfully.")
    return _reranker

def rerank_documents(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    Reranks a list of chunks based on a query.
    Each chunk is a dict containing at least {"text": str}.
    Returns a sorted list of chunks with a "rerank_score" key attached.
    """
    if not chunks:
        return []
        
    model = get_reranker_model()
    
    # Form pairs: [[query, text1], [query, text2], ...]
    pairs = [[query, chunk["text"]] for chunk in chunks]
    
    # Predict relevance scores (higher means more relevant)
    scores = model.predict(pairs, convert_to_numpy=True).tolist()
    
    # Attach scores to chunks
    for idx, score in enumerate(scores):
        chunks[idx]["rerank_score"] = float(score)
        
    # Sort chunks by score in descending order
    sorted_chunks = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    
    # Return top_k results
    return sorted_chunks[:top_k]
