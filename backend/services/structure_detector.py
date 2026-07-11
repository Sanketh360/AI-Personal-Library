import statistics

def detect_pdf_median_font_size(pages: list[dict]) -> float:
    """Calculates the median font size across all blocks in a PDF to establish a body-text baseline."""
    sizes = []
    for page in pages:
        for block in page.get("blocks", []):
            size = block.get("font_size", 0.0)
            if size > 0:
                sizes.append(size)
    if not sizes:
        return 10.0  # default fallback
    return statistics.median(sizes)

def detect_headings(pages: list[dict], file_format: str) -> list[dict]:
    """
    Scans pages and extracts headings/chapters with their location.
    Returns: [{"title": str, "level": int, "page_number": int}]
    """
    headings = []
    
    if file_format == ".pdf":
        median_size = detect_pdf_median_font_size(pages)
        # Heading threshold: at least 2.5pt larger than body text or 25% larger, and bold
        threshold = max(median_size + 2.5, median_size * 1.25)
        
        for page in pages:
            for block in page.get("blocks", []):
                text = block.get("text", "").strip()
                # Skip header/footer artifacts like page numbers or very short lines of junk
                if not text or len(text) < 3 or len(text) > 120:
                    continue
                
                size = block.get("font_size", 0.0)
                is_bold = block.get("is_bold", False)
                
                # Check if it looks like a heading
                if (size >= threshold and is_bold) or (size >= threshold + 4.0):
                    # Guess heading level based on size
                    if size >= threshold + 8.0:
                        level = 1
                    elif size >= threshold + 4.0:
                        level = 2
                    else:
                        level = 3
                        
                    headings.append({
                        "title": text,
                        "level": level,
                        "page_number": page["page_number"]
                    })
                    
    elif file_format in [".docx", ".epub", ".txt", ".md"]:
        # DOCX, EPUB, TXT, MD parser already provides heading_level in paragraph/element data
        for page in pages:
            # Check elements/paragraphs
            items = page.get("paragraphs", []) or page.get("elements", [])
            for item in items:
                heading_level = item.get("heading_level")
                if heading_level is not None:
                    headings.append({
                        "title": item["text"],
                        "level": heading_level,
                        "page_number": page["page_number"]
                    })
                    
    # Remove duplicate consecutive headings
    unique_headings = []
    seen = set()
    for h in headings:
        key = (h["title"].lower(), h["page_number"])
        if key not in seen:
            seen.add(key)
            unique_headings.append(h)
            
    return unique_headings

def annotate_pages_with_structure(pages: list[dict], headings: list[dict]) -> list[dict]:
    """
    Annotates each page structure with the active heading.
    If no heading has been encountered yet, uses the document name.
    """
    if not headings:
        # Default fallback: no headings detected
        for page in pages:
            page["active_heading"] = "Document Body"
        return pages
        
    # Sort headings by page number
    sorted_headings = sorted(headings, key=lambda x: x["page_number"])
    
    current_heading = "Document Introduction"
    heading_idx = 0
    num_headings = len(sorted_headings)
    
    for page in pages:
        page_num = page["page_number"]
        
        # Check if we transitioned to a new heading on or before this page
        while heading_idx < num_headings and sorted_headings[heading_idx]["page_number"] <= page_num:
            current_heading = sorted_headings[heading_idx]["title"]
            heading_idx += 1
            
        page["active_heading"] = current_heading
        
    return pages
