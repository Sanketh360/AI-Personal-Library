import re

def estimate_tokens(text: str) -> int:
    """Estimates token count based on standard English word-to-token ratio (~1.3 tokens per word)."""
    words = text.split()
    return int(len(words) * 1.3)

def split_into_sentences(text: str) -> list[str]:
    """Splits a block of text into individual sentences using regular expressions."""
    # Split text but keep punctuation
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text)
    return [s.strip() for s in sentences if s.strip()]

def create_hierarchical_chunks(
    pages: list[dict], 
    target_token_size: int = 500, 
    sentence_overlap: int = 2
) -> list[dict]:
    """
    Creates hierarchical, structure-aware chunks from pages.
    Guarantees:
    - Chunks do not span across different chapters (active_headings).
    - Chunk boundaries are split on sentence ends.
    - Carrying over overlaps of N sentences.
    
    Returns: A list of chunks:
    [
        {
            "text": str,
            "chapter_title": str,
            "page_number": int,
            "chunk_index": int
        }
    ]
    """
    chunks = []
    chunk_index = 0
    
    current_chapter = None
    current_buffer = []
    current_page_num = 1
    
    for page in pages:
        page_num = page["page_number"]
        page_text = page["text"]
        active_heading = page.get("active_heading", "Document Body")
        
        # If chapter changes, flush the buffer
        if current_chapter is not None and active_heading != current_chapter:
            if current_buffer:
                chunk_text = " ".join(current_buffer)
                chunks.append({
                    "text": chunk_text,
                    "chapter_title": current_chapter,
                    "page_number": current_page_num,
                    "chunk_index": chunk_index
                })
                chunk_index += 1
            current_buffer = []
            
        current_chapter = active_heading
        current_page_num = page_num
        
        # Split page text into sentences
        sentences = split_into_sentences(page_text)
        
        for sentence in sentences:
            current_buffer.append(sentence)
            
            # Check size
            buffer_text = " ".join(current_buffer)
            token_count = estimate_tokens(buffer_text)
            
            if token_count >= target_token_size:
                # Flush chunk
                chunks.append({
                    "text": buffer_text,
                    "chapter_title": current_chapter,
                    "page_number": current_page_num,
                    "chunk_index": chunk_index
                })
                chunk_index += 1
                
                # Overlap: keep the last N sentences
                if len(current_buffer) > sentence_overlap:
                    current_buffer = current_buffer[-sentence_overlap:]
                else:
                    current_buffer = []
                    
    # Flush remaining buffer
    if current_buffer:
        buffer_text = " ".join(current_buffer)
        chunks.append({
            "text": buffer_text,
            "chapter_title": current_chapter,
            "page_number": current_page_num,
            "chunk_index": chunk_index
        })
        
    return chunks
