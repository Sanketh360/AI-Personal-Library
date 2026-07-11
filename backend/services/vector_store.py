import os
import chromadb
from chromadb.config import Settings

# Global persistent ChromaDB client & collection cache
_chroma_client = None
_collection = None

def get_chroma_client():
    """Initializes and caches the persistent ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        chroma_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        print(f"Initializing ChromaDB persistent client at: {chroma_path}")
        _chroma_client = chromadb.PersistentClient(path=chroma_path)
    return _chroma_client

def get_collection():
    """Fetches or creates the default collection in ChromaDB."""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        # Cosine distance is standard for Nomic/BGE embeddings
        _collection = client.get_or_create_collection(
            name="library_chunks",
            metadata={"hnsw:space": "cosine"}
        )
    return _collection

def add_chunks_to_vector_store(chunks: list[dict], embeddings: list[list[float]]):
    """
    Saves a list of document chunks and their pre-calculated dense embeddings to ChromaDB.
    Each chunk is a dict: {"id": str, "book_id": str, "chapter_title": str, "page_number": int, "text": str}
    """
    collection = get_collection()
    
    ids = []
    documents = []
    metadatas = []
    
    for idx, chunk in enumerate(chunks):
        ids.append(chunk["id"])
        documents.append(chunk["text"])
        metadatas.append({
            "book_id": chunk["book_id"],
            "chapter_title": chunk["chapter_title"] or "",
            "page_number": chunk["page_number"] or 0
        })
        
    if ids:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

def delete_book_vectors(book_id: str):
    """Deletes all vector embeddings associated with a specific book_id."""
    collection = get_collection()
    # Delete where book_id matches
    collection.delete(where={"book_id": book_id})

def search_dense_vectors(
    query_embedding: list[float], 
    limit: int = 10, 
    book_id: str = None
) -> list[dict]:
    """
    Queries ChromaDB using the query's dense embedding.
    Returns: list of dicts [{"chunk_id": str, "score": float}] (score is cosine similarity)
    """
    collection = get_collection()
    
    where_filter = None
    if book_id:
        where_filter = {"book_id": book_id}
        
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        where=where_filter
    )
    
    formatted_results = []
    if results and results["ids"] and results["ids"][0]:
        ids = results["ids"][0]
        distances = results["distances"][0]
        
        for chunk_id, distance in zip(ids, distances):
            # ChromaDB returns cosine distance.
            # Convert cosine distance [0, 2] to similarity score [0, 1] -> similarity = 1 - distance
            similarity = 1.0 - distance
            formatted_results.append({
                "chunk_id": chunk_id,
                "score": similarity
            })
            
    return formatted_results
