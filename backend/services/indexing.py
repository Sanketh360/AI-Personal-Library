import os
import uuid
import threading
from services.database import SessionLocal, Book, Chunk, add_chunk_to_fts
from services.parser import extract_document_pages
from services.structure_detector import detect_headings, annotate_pages_with_structure
from services.chunker import create_hierarchical_chunks
from services.embedding import embed_documents
from services.vector_store import add_chunks_to_vector_store

# Lock to ensure sequential book indexing (CPU/RAM optimization)
indexing_lock = threading.Lock()

def run_indexing_pipeline(book_id: str, file_path: str):
    """
    Sequential indexing pipeline.
    Parses, structure-detects, chunks, embeds, and saves the document.
    """
    print(f"Pipeline: Requesting lock for book_id: {book_id}")
    with indexing_lock:
        print(f"Pipeline: Lock acquired. Starting parsing for: {file_path}")
        db = SessionLocal()
        
        # Load book details
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            print(f"Pipeline: Book record not found for {book_id}")
            db.close()
            return
            
        try:
            # 1. Update status to processing
            book.status = "processing"
            db.commit()
            
            # 2. Extract raw text and page mappings
            pages = extract_document_pages(file_path)
            ext = os.path.splitext(file_path)[1].lower()
            
            # 3. Heading and structure analysis
            headings = detect_headings(pages, ext)
            pages = annotate_pages_with_structure(pages, headings)
            
            # 4. Hierarchical token chunking
            chunks_data = create_hierarchical_chunks(pages, target_token_size=500)
            if not chunks_data:
                raise ValueError("No text chunks could be created. Is the file empty or unreadable?")
                
            # 5. Generate embeddings in batches (avoids PyTorch peak memory consumption)
            batch_size = 16
            all_embeddings = []
            chunk_texts = [c["text"] for c in chunks_data]
            
            for i in range(0, len(chunk_texts), batch_size):
                batch = chunk_texts[i:i+batch_size]
                batch_embeddings = embed_documents(batch)
                all_embeddings.extend(batch_embeddings)
                
            # 6. Save database chunk entries and list for vector store
            db_chunks = []
            chroma_chunks = []
            
            for idx, chunk_info in enumerate(chunks_data):
                chunk_uuid = str(uuid.uuid4())
                
                db_chunk = Chunk(
                    id=chunk_uuid,
                    book_id=book_id,
                    chapter_title=chunk_info["chapter_title"],
                    page_number=chunk_info["page_number"],
                    chunk_index=chunk_info["chunk_index"],
                    text=chunk_info["text"]
                )
                db_chunks.append(db_chunk)
                
                chroma_chunks.append({
                    "id": chunk_uuid,
                    "book_id": book_id,
                    "chapter_title": chunk_info["chapter_title"],
                    "page_number": chunk_info["page_number"],
                    "text": chunk_info["text"]
                })
                
            # Save chunks to SQLite
            db.add_all(db_chunks)
            db.commit()
            
            # Add chunks to FTS5 virtual table
            for db_chunk in db_chunks:
                add_chunk_to_fts(db, db_chunk.id, db_chunk.text)
            db.commit()
            
            # Save to ChromaDB
            add_chunks_to_vector_store(chroma_chunks, all_embeddings)
            
            # 7. Complete Book stats
            book.status = "completed"
            book.num_chunks = len(chunks_data)
            book.pages = len(pages)
            book.error_message = None
            db.commit()
            print(f"Pipeline: Successfully indexed book: {book.title}")
            
        except Exception as e:
            db.rollback()
            book.status = "failed"
            book.error_message = str(e)
            db.commit()
            print(f"Pipeline: Failed indexing book {book.title}: {e}")
        finally:
            db.close()
