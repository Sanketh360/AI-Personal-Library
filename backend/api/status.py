import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from services.database import get_db, Book

router = APIRouter(prefix="/api", tags=["status"])

@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    """Returns library index statistics."""
    total_books = db.query(Book).count()
    completed = db.query(Book).filter(Book.status == "completed").count()
    processing = db.query(Book).filter(Book.status == "processing").count()
    queued = db.query(Book).filter(Book.status == "queued").count()
    failed = db.query(Book).filter(Book.status == "failed").count()
    
    return {
        "status": "healthy",
        "embedding_model": os.getenv("EMBEDDING_MODEL_NAME"),
        "reranker_model": os.getenv("RERANKER_MODEL_NAME"),
        "statistics": {
            "total_books": total_books,
            "completed": completed,
            "processing": processing,
            "queued": queued,
            "failed": failed
        }
    }
