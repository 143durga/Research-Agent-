"""V1.1 regression tests: SSRF, upload/URL import safety, XSS, input validation, auth, rate limiting."""
import io
import socket
import pytest
from safe_fetch import validate_url, fetch_pdf, UnsafeURLError, FetchError
from security import rate_limited


SSRF_URLS = [
    "http://127.0.0.1/a.pdf", "http://localhost/a.pdf", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/a.pdf", "http://192.168.1.10/a.pdf", "http://172.16.0.1/a.pdf", "http://[::1]/a.pdf",
    "http://[::ffff:127.0.0.1]/a.pdf", "http://0.0.0.0/a.pdf", "http://100.64.0.1/a.pdf",
    "file:///etc/passwd", "ftp://example.com/a.pdf", "gopher://example.com/", "javascript:alert(1)",
    "http://user:pw@example.com/a.pdf", "http://example.com:8080/a.pdf", "", None, 42,
]


def test_ssrf_urls_rejected():
    for url in SSRF_URLS:
        with pytest.raises(UnsafeURLError):
            validate_url(url)


class _Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]
    def close(self): pass


def _public_dns(monkeypatch, host="papers.example.test"):
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))] if h == host else real(h, *a, **k))


def test_redirect_to_internal_address_is_blocked(monkeypatch, tmp_path):
    _public_dns(monkeypatch)
    monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: _Resp(302, headers={"Location": "http://169.254.169.254/x"}))
    with pytest.raises(UnsafeURLError):
        fetch_pdf("https://papers.example.test/a.pdf", str(tmp_path / "o.pdf"), 1024 * 1024)


def test_fetch_rejects_non_pdf_and_oversize_and_accepts_pdf(monkeypatch, tmp_path):
    _public_dns(monkeypatch)
    out = str(tmp_path / "o.pdf")
    monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: _Resp(200, b"<html>not a pdf</html>"))
    with pytest.raises(FetchError):
        fetch_pdf("https://papers.example.test/a", out, 1024 * 1024)
    monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: _Resp(200, b"%PDF-1.4" + b"x" * 5000))
    with pytest.raises(FetchError):
        fetch_pdf("https://papers.example.test/a", out, 1000)
    import os
    assert not os.path.exists(out)  # partial download removed
    monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: _Resp(200, b"%PDF-1.4 ok"))
    assert fetch_pdf("https://papers.example.test/a", out, 1024 * 1024) > 0
    monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: _Resp(404))
    with pytest.raises(FetchError):
        fetch_pdf("https://papers.example.test/a", out, 1024)


def test_api_rejects_internal_and_invalid_urls(client):
    pid = client.post("/api/papers/import", json={"title": "SSRF target paper"}).get_json()["paper_id"]
    for url in ["http://127.0.0.1:5000/api/search", "http://169.254.169.254/", "file:///etc/passwd", "not a url", None]:
        r = client.post(f"/api/papers/{pid}/import-pdf-from-url", json={"url": url})
        assert r.status_code == 400, url
        assert "URL rejected" in r.get_json()["error"]
    assert client.post("/api/papers/999999/import-pdf-from-url", json={"url": "https://x.test/a.pdf"}).status_code == 404


def test_javascript_urls_never_stored_or_rendered(client):
    r = client.post("/api/papers/import", json={"title": "XSS URL paper", "source_url": "javascript:alert(1)", "pdf_url": "data:text/html,x"}).get_json()
    html = client.get(f"/paper/{r['paper_id']}").get_data(as_text=True)
    assert "javascript:" not in html and "data:text/html" not in html


def test_html_in_titles_is_escaped(client):
    pid = client.post("/api/papers/import", json={"title": "<script>alert(1)</script> Tricky", "abstract": "<img src=x onerror=alert(1)>"}).get_json()["paper_id"]
    for path in (f"/paper/{pid}", "/library", "/"):
        body = client.get(path).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body and "<img src=x onerror" not in body


def test_input_validation(client):
    assert client.post("/api/compare", json={"paper_ids": "1,2"}).status_code == 400
    assert client.post("/api/compare", json={"paper_ids": [1, "2; DROP TABLE papers"]}).status_code == 400
    assert client.post("/api/gaps/find", json={"paper_ids": [True]}).status_code == 400
    assert client.post("/api/search", json={"query": "x", "sources": ["evil"]}).status_code == 400
    assert client.post("/api/search", json={"query": "x", "year": "2020; --"}).status_code == 400
    assert client.post("/api/search", json={"query": "x" * 400}).status_code == 400
    assert client.post("/api/papers/424242/notes", json={"content": "n"}).status_code == 404
    assert client.post("/api/papers/424242/chat", json={"question": "q"}).status_code == 404
    assert client.post("/api/projects/424242/papers", json={"paper_id": 1}).status_code in (404, 400)
    assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").is_json


def test_sql_injection_in_text_fields_is_inert(client):
    evil = "x'); DROP TABLE papers;--"
    pid = client.post("/api/papers/import", json={"title": evil, "authors": [evil]}).get_json()["paper_id"]
    client.post(f"/api/papers/{pid}/tags", json={"name": evil})
    assert client.get("/library").status_code == 200
    from db.database import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT title FROM papers WHERE id=?", (pid,))
        assert cur.fetchone()["title"] == evil


def test_oversized_upload_rejected_with_json(client):
    old = client.application.config["MAX_CONTENT_LENGTH"]
    client.application.config["MAX_CONTENT_LENGTH"] = 2048
    try:
        r = client.post("/api/papers/upload", data={"file": (io.BytesIO(b"%PDF-1.4" + b"0" * 10000), "big.pdf")}, content_type="multipart/form-data")
        assert r.status_code == 413 and "maximum upload size" in r.get_json()["error"]
    finally:
        client.application.config["MAX_CONTENT_LENGTH"] = old


def test_path_traversal_filename_is_neutralised(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        data = f.read()
    r = client.post("/api/papers/upload", data={"file": (io.BytesIO(data), "../../../../tmp/evil.pdf"), "title": "Traversal Paper"}, content_type="multipart/form-data")
    assert r.status_code == 200
    import os
    assert not os.path.exists("/tmp/evil.pdf")


def test_security_headers_and_no_wildcard_bind(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "127.0.0.1" in open("app.py").read()


def test_rate_limiter_blocks_after_limit():
    assert [rate_limited("t-key", 2) for _ in range(3)] == [False, False, True]


def test_api_key_constant_time_gate_accepts_correct_key(client):
    client.application.config["APP_API_KEY"] = "s3cret"
    try:
        assert client.post("/api/search", json={"query": ""}, headers={"X-API-Key": "s3cret"}).status_code == 400  # past auth
        assert client.post("/api/search", json={"query": "x"}, headers={"X-API-Key": "wrong"}).status_code == 401
    finally:
        client.application.config["APP_API_KEY"] = ""
