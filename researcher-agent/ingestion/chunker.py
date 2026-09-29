"""
Splits detected sections into overlapping word-based chunks suitable for
embedding + retrieval. Each chunk retains its section name and page range so
every retrieved chunk can be cited back to a specific place in the paper.
"""
from typing import List, Dict

DEFAULT_CHUNK_WORDS = 220
DEFAULT_OVERLAP_WORDS = 40


def chunk_sections(sections: List[Dict], chunk_words: int = DEFAULT_CHUNK_WORDS,
                    overlap_words: int = DEFAULT_OVERLAP_WORDS) -> List[Dict]:
    chunks = []
    chunk_index = 0
    for section in sections:
        words = section["content"].split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + chunk_words, len(words))
            piece = " ".join(words[start:end]).strip()
            if piece:
                chunks.append({
                    "section_name": section["section_name"],
                    "page": section.get("page_start"),
                    "chunk_index": chunk_index,
                    "content": piece,
                    "token_count": len(piece.split()),
                })
                chunk_index += 1
            if end == len(words):
                break
            start = end - overlap_words
    return chunks
