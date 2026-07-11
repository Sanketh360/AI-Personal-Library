from sqlalchemy import text
from services.database import SessionLocal
from services.retrieval import retrieve_hybrid

def search_book(book_id: str, query: str) -> str:
    """
    Search for information within a single specific book in the library.
    Use this tool when the user has selected a book or is asking a question about a single book.
    
    Args:
        book_id: The unique identifier/hash of the book to search within.
        query: The search query or question to retrieve matching passages for.
        
    Returns:
        A formatted string of relevant text passages, page numbers, and chapter headings.
    """
    db = SessionLocal()
    try:
        chunks = retrieve_hybrid(db, query, limit=6, book_id=book_id)
        if not chunks:
            return "No matching passages found in this book."
            
        formatted_passages = []
        for idx, chunk in enumerate(chunks):
            formatted_passages.append(
                f"[Document Passage {idx + 1}]\n"
                f"Book: {chunk['book_title']}\n"
                f"Chapter: {chunk['chapter_title'] or 'Unknown'}\n"
                f"Page: {chunk['page_number'] or 'Unknown'}\n"
                f"Content: {chunk['text']}\n"
                f"----------------------------------------"
            )
        return "\n\n".join(formatted_passages)
    finally:
        db.close()

def search_library(query: str) -> str:
    """
    Search for information across all books in the library.
    Use this tool when the user is asking a general question across the entire collection.
    
    Args:
        query: The search query or question to search the library for.
        
    Returns:
        A formatted string of relevant passages, including the book names, chapters, and pages.
    """
    db = SessionLocal()
    try:
        chunks = retrieve_hybrid(db, query, limit=8, book_id=None)
        if not chunks:
            return "No matching passages found across the library."
            
        formatted_passages = []
        for idx, chunk in enumerate(chunks):
            formatted_passages.append(
                f"[Document Passage {idx + 1}]\n"
                f"Book: {chunk['book_title']}\n"
                f"Chapter: {chunk['chapter_title'] or 'Unknown'}\n"
                f"Page: {chunk['page_number'] or 'Unknown'}\n"
                f"Content: {chunk['text']}\n"
                f"----------------------------------------"
            )
        return "\n\n".join(formatted_passages)
    finally:
        db.close()

def compare_books(book_ids: list, query: str) -> str:
    """
    Search and compare information across a list of specific books.
    Use this tool when the user specifically selects multiple books to compare, contrast, or analyze together.
    
    Args:
        book_ids: A list of unique book IDs to search and compare.
        query: The question or comparison criteria to search for.
        
    Returns:
        A formatted string separating the retrieved passages by book, allowing comparison.
    """
    db = SessionLocal()
    try:
        if not book_ids:
            return "Error: No books were selected for comparison."
            
        formatted_results = []
        
        for book_id in book_ids:
            # Query each book separately to guarantee representation from all books
            chunks = retrieve_hybrid(db, query, limit=3, book_id=book_id)
            
            book_passages = []
            if chunks:
                book_title = chunks[0]['book_title']
                book_passages.append(f"=== Passages for Book: {book_title} ===")
                for idx, chunk in enumerate(chunks):
                    book_passages.append(
                        f"Passage {idx + 1}:\n"
                        f"Chapter: {chunk['chapter_title'] or 'Unknown'}\n"
                        f"Page: {chunk['page_number'] or 'Unknown'}\n"
                        f"Content: {chunk['text']}\n"
                    )
            else:
                # Try to get book title from database if no chunks found
                book_row = db.execute(
                    text("SELECT title FROM books WHERE id = :id"), 
                    {"id": book_id}
                ).fetchone()
                title = book_row[0] if book_row else "Unknown Book"
                book_passages.append(f"=== No matching passages found for Book: {title} ===")
                
            formatted_results.append("\n".join(book_passages))
            
        return "\n\n========================================\n\n".join(formatted_results)
    finally:
        db.close()
