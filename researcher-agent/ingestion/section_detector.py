"""
Heuristic section detection for academic papers.

This is intentionally a rule-based (not ML) pass: academic papers vary a lot,
so instead of guessing structure with an LLM (which risks inventing sections
that aren't there), we scan for common heading text and split on it. Any
paper section this app claims to have found corresponds to real heading text
that was actually seen in the extracted PDF text.

Papers that don't have a given section (e.g. no explicit "Limitations"
heading) simply won't produce that section - callers must not assume every
section exists.
"""
import re
from typing import List, Dict

# Canonical section name -> regex patterns that match a heading line for it.
# Ordered roughly by typical paper structure.
SECTION_PATTERNS = [
    ("abstract", [r"^abstract$"]),
    ("introduction", [r"^\d*\.?\s*introduction$"]),
    ("related_work", [r"^\d*\.?\s*related work$", r"^\d*\.?\s*background$", r"^\d*\.?\s*literature review$"]),
    ("methodology", [r"^\d*\.?\s*method(ology)?$", r"^\d*\.?\s*approach$", r"^\d*\.?\s*proposed (method|approach)$", r"^\d*\.?\s*system design$"]),
    ("dataset", [r"^\d*\.?\s*dataset(s)?$", r"^\d*\.?\s*data collection$"]),
    ("experiments", [r"^\d*\.?\s*experiment(s|al setup)?$", r"^\d*\.?\s*evaluation$", r"^\d*\.?\s*experimental design$"]),
    ("results", [r"^\d*\.?\s*results?$", r"^\d*\.?\s*findings$"]),
    ("discussion", [r"^\d*\.?\s*discussion$"]),
    ("limitations", [r"^\d*\.?\s*limitations?$", r"^\d*\.?\s*threats to validity$"]),
    ("conclusion", [r"^\d*\.?\s*conclusion(s)?$", r"^\d*\.?\s*conclusion and future work$", r"^\d*\.?\s*summary$"]),
    ("future_work", [r"^\d*\.?\s*future work$"]),
    ("acknowledgments", [r"^\d*\.?\s*acknowledge?ments?$"]),
    ("references", [r"^\d*\.?\s*references$", r"^\d*\.?\s*bibliography$"]),
]

_COMPILED = [(name, [re.compile(p, re.IGNORECASE) for p in patterns]) for name, patterns in SECTION_PATTERNS]

MIN_HEADING_LEN = 2
MAX_HEADING_LEN = 60


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not (MIN_HEADING_LEN <= len(stripped) <= MAX_HEADING_LEN):
        return False
    # Headings are typically short lines without terminal punctuation
    if stripped.endswith((".", ",", ";")):
        return False
    return True


def detect_sections(pages: List[Dict]) -> List[Dict]:
    """pages: [{"page": int, "text": str}, ...]
    returns: [{"section_name": str, "content": str, "page_start": int, "page_end": int, "order_index": int}]
    Text that doesn't fall under any recognized heading is bucketed as 'other' so
    nothing is discarded, but 'other' is never presented as if it were a named section.
    """
    sections: List[Dict] = []
    current = {"section_name": "other", "content": "", "page_start": pages[0]["page"] if pages else None, "page_end": None, "order_index": 0}
    order = 0

    for page in pages:
        page_num = page["page"]
        lines = page["text"].split("\n")
        for line in lines:
            matched_section = None
            if _looks_like_heading(line):
                normalized = line.strip().lower()
                for name, patterns in _COMPILED:
                    if any(p.match(normalized) for p in patterns):
                        matched_section = name
                        break
            if matched_section:
                if current["content"].strip():
                    current["page_end"] = page_num
                    sections.append(current)
                order += 1
                current = {"section_name": matched_section, "content": "", "page_start": page_num, "page_end": None, "order_index": order}
            else:
                current["content"] += line + "\n"
        current["page_end"] = page_num

    if current["content"].strip():
        sections.append(current)

    return sections
