import os
import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import text

# Base model class
Base = declarative_base()

class Book(Base):
    __tablename__ = "books"

    id = Column(String, primary_key=True)  # Hash of file
    title = Column(String, nullable=False)
    author = Column(String, nullable=True)
    format = Column(String, nullable=False)
    pages = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=False)
    num_chunks = Column(Integer, default=0)
    indexed_time = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="queued")  # queued, processing, completed, failed
    error_message = Column(String, nullable=True)
    file_hash = Column(String, unique=True, nullable=False)
    file_path = Column(String, nullable=True)  # Actual saved file path on disk

    chunks = relationship("Chunk", back_populates="book", cascade="all, delete-orphan")

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String, primary_key=True)  # UUID
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_title = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)

    book = relationship("Book", back_populates="chunks")

# Database session setup
DATABASE_URL = os.getenv("SQLITE_DB_URL", "sqlite:///./database/library.db")

# Ensure the database directory exists
db_dir = os.path.dirname(DATABASE_URL.replace("sqlite:///", ""))
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Needed for SQLite multi-threading
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Create standard tables
    Base.metadata.create_all(bind=engine)
    
    # Create SQLite FTS5 table for fast sparse text search
    with engine.connect() as conn:
        # Enable Write-Ahead Logging (WAL) mode for concurrency safety
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.commit()
        
        # Check if virtual table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_fts';")
        ).fetchone()
        
        if not result:
            # Create virtual table for FTS5
            # chunk_id is unindexed (we just retrieve it) and text is indexed
            conn.execute(
                text("CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, text);")
            )
            conn.commit()

        # Schema Migration: Add file_path column if not present in legacy database file
        columns_info = conn.execute(text("PRAGMA table_info(books);")).fetchall()
        col_names = [col[1] for col in columns_info]
        if "file_path" not in col_names:
            print("Database Migration: Adding file_path column to books table...")
            conn.execute(text("ALTER TABLE books ADD COLUMN file_path VARCHAR;"))
            conn.commit()

def add_chunk_to_fts(db_session, chunk_id: str, text_content: str):
    """Inserts a chunk's text content into the SQLite FTS5 virtual table."""
    db_session.execute(
        text("INSERT INTO chunk_fts (chunk_id, text) VALUES (:chunk_id, :text)"),
        {"chunk_id": chunk_id, "text": text_content}
    )

def remove_book_from_fts(db_session, book_id: str):
    """Cleans up all FTS entries associated with a book's chunks when a book is deleted."""
    # Find all chunk IDs for the book
    chunk_ids = [r[0] for r in db_session.execute(
        text("SELECT id FROM chunks WHERE book_id = :book_id"),
        {"book_id": book_id}
    ).fetchall()]
    
    if chunk_ids:
        # Delete from FTS table
        from sqlalchemy import bindparam
        stmt = text("DELETE FROM chunk_fts WHERE chunk_id IN :chunk_ids").bindparams(
            bindparam("chunk_ids", expanding=True)
        )
        db_session.execute(stmt, {"chunk_ids": list(chunk_ids)})

def search_fts(db_session, query: str, limit: int = 10, book_id: str = None) -> list:
    """
    Searches the FTS5 virtual table.
    If book_id is provided, filters results to chunks belonging only to that book.
    Returns list of dicts: [{"chunk_id": str, "score": float}]
    """
    # Sanitize the query for FTS5 (avoid syntax errors on special characters)
    sanitized_query = query.replace('"', '').replace("'", "")
    if not sanitized_query.strip():
        return []
    
    # SQLite FTS5 rank ordering. Lower rank values mean better matches, 
    # but we will convert it to a similarity score (higher is better) for RRF/Reranking.
    if book_id:
        sql = """
            SELECT f.chunk_id, f.text, bm25(chunk_fts) as rank 
            FROM chunk_fts f
            JOIN chunks c ON f.chunk_id = c.id
            WHERE c.book_id = :book_id AND chunk_fts MATCH :query
            ORDER BY rank ASC
            LIMIT :limit
        """
        params = {"query": sanitized_query, "book_id": book_id, "limit": limit}
    else:
        sql = """
            SELECT chunk_id, text, bm25(chunk_fts) as rank 
            FROM chunk_fts
            WHERE chunk_fts MATCH :query
            ORDER BY rank ASC
            LIMIT :limit
        """
        params = {"query": sanitized_query, "limit": limit}
        
    try:
        results = db_session.execute(text(sql), params).fetchall()
        # bm25 rank is negative/positive depending on sqlite compile settings.
        # We return chunk_id and rank (relative order is what matters).
        return [{"chunk_id": r[0], "rank": r[2]} for r in results]
    except Exception as e:
        print(f"FTS search syntax error for query '{query}': {e}")
        # Fallback to simple LIKE search if MATCH syntax errors
        if book_id:
            sql_fallback = """
                SELECT id, text FROM chunks 
                WHERE book_id = :book_id AND text LIKE :query_like
                LIMIT :limit
            """
            params_fallback = {"query_like": f"%{query}%", "book_id": book_id, "limit": limit}
        else:
            sql_fallback = """
                SELECT id, text FROM chunks 
                WHERE text LIKE :query_like
                LIMIT :limit
            """
            params_fallback = {"query_like": f"%{query}%", "limit": limit}
            
        results = db_session.execute(text(sql_fallback), params_fallback).fetchall()
        return [{"chunk_id": r[0], "rank": float(idx)} for idx, r in enumerate(results)]
