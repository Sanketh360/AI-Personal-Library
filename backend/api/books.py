import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from services.database import get_db, Book, remove_book_from_fts
from services.vector_store import delete_book_vectors
from services.upload_validator import sanitize_filename

router = APIRouter(prefix="/api", tags=["books"])

BOOKS_DIR = os.getenv("BOOKS_DIR", "./books")

@router.get("/books")
def list_books(db: Session = Depends(get_db)):
    """Returns a list of all books in the library."""
    books = db.query(Book).all()
    return [
        {
            "id": b.id,
            "title": b.title,
            "author": b.author,
            "format": b.format,
            "pages": b.pages,
            "file_size": b.file_size,
            "num_chunks": b.num_chunks,
            "indexed_time": b.indexed_time.isoformat() if b.indexed_time else None,
            "status": b.status,
            "error_message": b.error_message
        }
        for b in books
    ]

@router.delete("/books/{book_id}")
def delete_book(book_id: str, db: Session = Depends(get_db)):
    """Deletes a book, its files, database logs, and vector database entries."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
        
    try:
        # 1. Clean vectors from ChromaDB
        delete_book_vectors(book_id)
        
        # 2. Clean from FTS5 index
        remove_book_from_fts(db, book_id)
        
        # 3. Delete file
        # Use stored file_path directly (resolving Issue 3)
        file_path = book.file_path
        if not file_path:
            # Fallback path reconstruction for legacy entries
            file_name = sanitize_filename(f"{book.title.replace(' ', '_')}{book.format}")
            file_path = os.path.join(BOOKS_DIR, file_name)
            
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            
        # 4. Delete DB rows (cascade deletes chunks automatically)
        db.delete(book)
        db.commit()
        
        return {"status": "success", "message": f"Deleted book '{book.title}'"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete book: {e}")
