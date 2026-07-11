import os
import re
import fitz  # PyMuPDF
from docx import Document
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

def clean_extracted_text(text: str) -> str:
    """Cleans extracted text by resolving duplicate whitespace, line breaks, etc."""
    if not text:
        return ""
    # Replace multiple spaces with a single space
    text = re.sub(r'[ \t]+', ' ', text)
    # Replace more than two newlines with exactly two newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def parse_pdf(file_path: str) -> list[dict]:
    """
    Parses a PDF using PyMuPDF (fitz).
    Returns a list of pages: [{"page_number": int, "text": str, "blocks": list}]
    Each block in blocks has: {"text": str, "font_size": float, "is_bold": bool} for structure detection.
    """
    doc = fitz.open(file_path)
    pages = []
    
    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        page_text = page.get_text("text")
        
        # Extract detailed blocks with formatting for structure detection
        blocks_data = []
        try:
            # get_text("dict") returns blocks, lines, spans with styling
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    block_text = ""
                    max_font_size = 0.0
                    is_bold = False
                    
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            span_text = span.get("text", "")
                            block_text += span_text + " "
                            font_size = span.get("size", 0.0)
                            if font_size > max_font_size:
                                max_font_size = font_size
                            # Check flags for bold (font flags bit 4 (16) is bold)
                            flags = span.get("flags", 0)
                            if flags & 16:
                                is_bold = True
                            elif "bold" in span.get("font", "").lower():
                                is_bold = True
                                
                    block_text = clean_extracted_text(block_text)
                    if block_text:
                        blocks_data.append({
                            "text": block_text,
                            "font_size": max_font_size,
                            "is_bold": is_bold
                        })
        except Exception as e:
            print(f"Error extracting PDF block format on page {page_num}: {e}")
            # Fallback to plain text split if dict extraction fails
            blocks_data = [{"text": line, "font_size": 10.0, "is_bold": False} 
                           for line in page_text.split('\n') if line.strip()]
            
        pages.append({
            "page_number": page_num,
            "text": clean_extracted_text(page_text),
            "blocks": blocks_data
        })
        
    return pages

def parse_docx(file_path: str) -> list[dict]:
    """
    Parses a DOCX file using python-docx.
    Returns simulated pages: [{"page_number": int, "text": str, "paragraphs": list}]
    Each paragraph has styling metadata for heading detection.
    """
    doc = Document(file_path)
    paragraphs_data = []
    
    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
            
        # Determine heading level from paragraph style
        style_name = para.style.name.lower()
        heading_level = None
        if style_name.startswith("heading"):
            try:
                heading_level = int(style_name.split()[-1])
            except ValueError:
                # default to level 1 if styling name is just "Heading"
                heading_level = 1
                
        # Check inline bolding of runs as fallback
        is_bold = any(run.bold for run in para.runs if run.bold)
        
        paragraphs_data.append({
            "text": text,
            "style": para.style.name,
            "heading_level": heading_level,
            "is_bold": is_bold
        })

    # Since docx doesn't have native pages, we group text into simulated pages
    # of roughly 3000 characters (~500 words) for consistent retrieval sizes
    pages = []
    current_page_text = []
    current_page_char_count = 0
    current_page_paras = []
    page_num = 1
    
    for para in paragraphs_data:
        current_page_text.append(para["text"])
        current_page_paras.append(para)
        current_page_char_count += len(para["text"])
        
        if current_page_char_count > 3000:
            pages.append({
                "page_number": page_num,
                "text": clean_extracted_text("\n\n".join(current_page_text)),
                "paragraphs": current_page_paras
            })
            current_page_text = []
            current_page_paras = []
            current_page_char_count = 0
            page_num += 1
            
    if current_page_text:
        pages.append({
            "page_number": page_num,
            "text": clean_extracted_text("\n\n".join(current_page_text)),
            "paragraphs": current_page_paras
        })
        
    return pages

def parse_epub(file_path: str) -> list[dict]:
    """
    Parses an EPUB file using EbookLib.
    Returns simulated pages grouped by EPUB chapters/documents.
    """
    book = epub.read_epub(file_path)
    pages = []
    page_num = 1
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            html_content = item.get_content()
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract paragraphs and headings with tags intact for structure detection
            elements_data = []
            # Find all headings and paragraphs
            for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                text = el.get_text().strip()
                if not text:
                    continue
                
                tag_name = el.name
                heading_level = None
                if tag_name.startswith('h') and len(tag_name) == 2:
                    heading_level = int(tag_name[1])
                    
                elements_data.append({
                    "text": text,
                    "tag": tag_name,
                    "heading_level": heading_level,
                    "is_bold": tag_name.startswith('h')
                })
            
            if not elements_data:
                continue
                
            # Create a page for this chapter document
            chapter_text = "\n\n".join([el["text"] for el in elements_data])
            pages.append({
                "page_number": page_num,
                "text": clean_extracted_text(chapter_text),
                "elements": elements_data
            })
            page_num += 1
            
    return pages

def parse_text_or_markdown(file_path: str) -> list[dict]:
    """
    Parses plain TXT or Markdown files.
    Splits content into page-like chunks of ~3000 characters.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    
    pages = []
    current_page_text = []
    current_page_char_count = 0
    page_num = 1
    
    for para in paragraphs:
        # Simple Markdown heading parsing
        is_heading = para.startswith("#")
        heading_level = None
        if is_heading:
            match = re.match(r'^(#+)\s', para)
            if match:
                heading_level = len(match.group(1))
                
        para_data = {
            "text": para,
            "is_bold": is_heading,
            "heading_level": heading_level
        }
        
        current_page_text.append(para)
        current_page_char_count += len(para)
        
        if current_page_char_count > 3000:
            pages.append({
                "page_number": page_num,
                "text": clean_extracted_text("\n\n".join(current_page_text)),
                "paragraphs": [para_data]  # simplified representation
            })
            current_page_text = []
            current_page_char_count = 0
            page_num += 1
            
    if current_page_text:
        pages.append({
            "page_number": page_num,
            "text": clean_extracted_text("\n\n".join(current_page_text)),
            "paragraphs": []
        })
        
    return pages

def extract_document_pages(file_path: str) -> list[dict]:
    """
    Dispatch function to parse a document based on its extension.
    Returns: [{"page_number": int, "text": str, "formatting": list/dict}]
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        return parse_pdf(file_path)
    elif ext == ".docx":
        return parse_docx(file_path)
    elif ext in [".epub"]:
        return parse_epub(file_path)
    elif ext in [".txt", ".md"]:
        return parse_text_or_markdown(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}")
