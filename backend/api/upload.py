import os
import hashlib
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, File, UploadFile
from sqlalchemy.orm import Session
from services.database import get_db, Book
from services.upload_validator import validate_file, get_file_hash, sanitize_filename
from services.indexing import run_indexing_pipeline
from services.vector_store import delete_book_vectors

router = APIRouter(prefix="/api", tags=["upload"])

BOOKS_DIR = os.getenv("BOOKS_DIR", "./books")

@router.post("/upload")
async def upload_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Handles manual file upload, hashes contents, saves to file, and queues indexing."""
    # 1. Read file and validate
    contents = await file.read()
    file_size = len(contents)
    
    is_valid, err_msg = validate_file(file.filename, file_size)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)
        
    # 2. Hash check for duplicates
    file_hash = get_file_hash(contents)
    duplicate = db.query(Book).filter(Book.file_hash == file_hash).first()
    if duplicate:
        # If it failed previously, clean up old references and let user re-index. Otherwise, raise conflict.
        if duplicate.status == "completed":
            raise HTTPException(status_code=409, detail=f"Book already exists: {duplicate.title}")
        elif duplicate.status in ["failed", "queued", "processing"]:
            # Clean up stale vectors and indexes first (resolving Issue 4)
            try:
                delete_book_vectors(duplicate.id)
            except Exception as ve:
                print(f"Cleanup: Failed to delete duplicate book vectors: {ve}")
            
            # Delete old record to restart
            db.delete(duplicate)
            db.commit()
            
    # 3. Sanitize and save to books folder
    clean_filename = sanitize_filename(file.filename)
    dest_path = os.path.abspath(os.path.join(BOOKS_DIR, clean_filename))
    
    with open(dest_path, "wb") as f:
        f.write(contents)
        
    # 4. Insert Book record as queued (storing the actual file_path)
    book_id = file_hash
    title = os.path.splitext(clean_filename)[0].replace('_', ' ')
    ext = os.path.splitext(clean_filename)[1].lower()
    
    new_book = Book(
        id=book_id,
        title=title,
        author=None,
        format=ext,
        file_size=file_size,
        file_hash=file_hash,
        status="queued",
        file_path=dest_path  # Save actual file path (resolving Issue 3)
    )
    db.add(new_book)
    db.commit()
    
    # 5. Trigger Background Task sequentially
    background_tasks.add_task(run_indexing_pipeline, book_id, dest_path)
    
    return {
        "status": "queued",
        "book_id": book_id,
        "title": title
    }
