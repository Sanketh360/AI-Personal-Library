import os
import re
import hashlib
from sqlalchemy.orm import Session
from services.database import Book

# Allowed extensions and standard MIME types
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.epub', '.txt', '.md'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB limit

def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a filename to prevent path traversal and shell injection.
    Only allows alphanumeric characters, underscores, hyphens, and dots.
    """
    # Get only the base name (strip paths)
    base_name = os.path.basename(filename)
    # Split name and extension
    name, ext = os.path.splitext(base_name)
    # Clean the name (keep alphanumeric, hyphens, underscores)
    clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    # Ensure extension is lowercase
    clean_ext = ext.lower()
    return f"{clean_name}{clean_ext}"

def validate_file(filename: str, size: int) -> tuple[bool, str]:
    """
    Validates file extension and size.
    Returns (is_valid, error_message).
    """
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        
    if size > MAX_FILE_SIZE:
        return False, f"File size exceeds the limit of {MAX_FILE_SIZE / (1024 * 1024):.1f}MB."
        
    return True, ""

def get_file_hash(file_bytes: bytes) -> str:
    """Calculates the SHA-256 hash of file contents for duplicate detection."""
    sha256 = hashlib.sha256()
    sha256.update(file_bytes)
    return sha256.hexdigest()

def check_duplicate_by_hash(db: Session, file_hash: str) -> Book:
    """Checks if a book with the same file hash already exists in the database."""
    return db.query(Book).filter(Book.file_hash == file_hash).first()
