from ingestion.chunker import chunk_sections
from ingestion.section_detector import detect_sections
from ingestion.pipeline import upsert_paper_metadata, find_existing_paper
from providers.search.arxiv import ArxivProvider
from providers.search.semantic_scholar import SemanticScholarProvider
from providers.search.crossref import CrossrefProvider
import pytest


def test_section_detection_and_absence():
    pages = [{"page": 1, "text": "Abstract\nfoo bar\nIntroduction\nintro text\nConclusion\nend"}]
    names = [s["section_name"] for s in detect_sections(pages)]
    assert names == ["abstract", "introduction", "conclusion"]
    assert "limitations" not in names  # never assumes sections exist


def test_chunking_keeps_metadata():
    sections = [{"section_name": "results", "content": " ".join(["w"] * 500), "page_start": 3}]
    chunks = chunk_sections(sections, chunk_words=200, overlap_words=20)
    assert len(chunks) >= 3
    assert all(c["section_name"] == "results" and c["page"] == 3 for c in chunks)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_dedup_by_doi_and_title():
    a = upsert_paper_metadata({"title": "Dedup Paper", "doi": "10.1/abc", "authors": ["A B"]})
    b = upsert_paper_metadata({"title": "Different title same doi", "doi": "10.1/abc"})
    c = upsert_paper_metadata({"title": "  dedup paper "})
    assert a == b == c
    assert find_existing_paper(doi="10.9/none") is None


def test_missing_metadata_not_invented():
    pid = upsert_paper_metadata({"title": "Bare Paper X"})
    from db.database import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT doi, abstract, year, citation_count FROM papers WHERE id=?", (pid,))
        row = dict(cur.fetchone())
    assert all(v is None for v in row.values())


class _Resp:
    def __init__(self, status=200, js=None, text=""):
        self.status_code, self._js, self.text = status, js, text
    def json(self): return self._js


def test_semantic_scholar_parsing_and_errors(monkeypatch):
    payload = {"data": [{"title": "T", "authors": [{"name": "Al"}], "year": 2023, "venue": "V", "abstract": None,
                         "externalIds": {}, "citationCount": 4, "openAccessPdf": None, "url": "http://u", "paperId": "pid"}]}
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, payload))
    r = SemanticScholarProvider().search("q")[0]
    assert r.doi is None and r.abstract is None and r.open_access is False and r.citation_count == 4
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(429))
    with pytest.raises(ConnectionError):
        SemanticScholarProvider().search("q")


def test_crossref_parsing(monkeypatch):
    payload = {"message": {"items": [{"title": ["Cr Paper"], "DOI": "10.5/x", "author": [{"given": "A", "family": "B"}],
                                        "published": {"date-parts": [[2021]]}, "container-title": ["J"], "URL": "http://x"}]}}
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, payload))
    r = CrossrefProvider().search("q")[0]
    assert r.doi == "10.5/x" and r.year == 2021 and r.authors == ["A B"] and r.abstract is None


def test_arxiv_parsing(monkeypatch):
    xml = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1</id><title>Ax</title>
    <summary>sum</summary><published>2022-01-01T00:00:00Z</published><author><name>Z</name></author>
    <link rel="alternate" href="http://arxiv.org/abs/1"/><link title="pdf" href="http://arxiv.org/pdf/1"/></entry></feed>"""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, text=xml))
    r = ArxivProvider().search("q")[0]
    assert r.pdf_url == "http://arxiv.org/pdf/1" and r.year == 2022 and r.citation_count is None
