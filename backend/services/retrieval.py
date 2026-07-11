import os
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from services.embedding import embed_query
from services.vector_store import search_dense_vectors
from services.database import search_fts
from services.reranker import rerank_documents

# Performance optimizations for CPU-only systems
DISABLE_RERANKER = os.getenv("DISABLE_RERANKER", "false").lower() == "true"
DEFAULT_CANDIDATE_LIMIT = int(os.getenv("RERANKER_CANDIDATE_LIMIT", "8"))

def reciprocal_rank_fusion(
    dense_ids: list[str], 
    sparse_ids: list[str], 
    k: int = 60
) -> list[tuple[str, float]]:
    """
    Applies Reciprocal Rank Fusion (RRF) to combine dense and sparse rankings.
    Returns: list of tuples (chunk_id, rrf_score) sorted by score descending.
    """
    rrf_scores = {}
    
    # Process dense rank list
    for rank, chunk_id in enumerate(dense_ids):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
        
    # Process sparse rank list
    for rank, chunk_id in enumerate(sparse_ids):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
        
    # Sort by RRF score descending
    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

def retrieve_hybrid(
    db_session: Session, 
    query: str, 
    limit: int = 5, 
    book_id: str = None,
    candidate_limit: int = None
) -> list[dict]:
    """
    Coordinates the entire retrieval pipeline:
    1. Generate query embedding.
    2. Dense search in ChromaDB.
    3. Sparse FTS5 search in SQLite.
    4. Fuse results using Reciprocal Rank Fusion (RRF).
    5. Fetch chunk text and metadata from the SQLite database.
    6. Rerank top candidates using the CrossEncoder model.
    """
    if candidate_limit is None:
        candidate_limit = DEFAULT_CANDIDATE_LIMIT
        
    # 1. Generate query embedding
    query_embedding = embed_query(query)
    
    # 2. Dense search in ChromaDB
    dense_results = search_dense_vectors(query_embedding, limit=candidate_limit, book_id=book_id)
    dense_ids = [item["chunk_id"] for item in dense_results]
    
    # 3. Sparse search in SQLite FTS
    sparse_results = search_fts(db_session, query, limit=candidate_limit, book_id=book_id)
    # SQLite ranks are sorted ascending (lower rank is better). FTS function returns rank sorted.
    sparse_ids = [item["chunk_id"] for item in sparse_results]
    
    if not dense_ids and not sparse_ids:
        return []
        
    # 4. Reciprocal Rank Fusion (RRF)
    fused_scores = reciprocal_rank_fusion(dense_ids, sparse_ids, k=60)
    top_candidate_ids = [item[0] for item in fused_scores[:candidate_limit]]
    
    if not top_candidate_ids:
        return []
        
    # 5. Fetch full text and metadata from SQLite database
    # Construct parameterized query for SQLAlchemy with expanding bind parameter
    from sqlalchemy import bindparam
    sql = """
        SELECT c.id, c.text, c.page_number, c.chapter_title, b.title as book_title, c.book_id
        FROM chunks c
        JOIN books b ON c.book_id = b.id
        WHERE c.id IN :chunk_ids
    """
    stmt = text(sql).bindparams(bindparam("chunk_ids", expanding=True))
    # Execute query
    chunks_rows = db_session.execute(stmt, {"chunk_ids": list(top_candidate_ids)}).fetchall()
    
    # Map back to dictionaries
    chunks_dict = {
        row[0]: {
            "id": row[0],
            "text": row[1],
            "page_number": row[2],
            "chapter_title": row[3],
            "book_title": row[4],
            "book_id": row[5]
        }
        for row in chunks_rows
    }
    
    # Restore the RRF sorted order
    candidate_chunks = []
    for cid in top_candidate_ids:
        if cid in chunks_dict:
            candidate_chunks.append(chunks_dict[cid])
            
    # 6. Rerank top candidates using CrossEncoder reranker
    if DISABLE_RERANKER or not candidate_chunks:
        return candidate_chunks[:limit]
        
    reranked_chunks = rerank_documents(query, candidate_chunks, top_k=limit)
    return reranked_chunks
