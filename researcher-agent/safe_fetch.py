"""
SSRF-hardened PDF downloader for URL-based imports.

Defenses:
- only http/https, no credentials in the URL, only ports 80/443 by default
- the hostname is resolved and EVERY resolved address must be public
  (no loopback, private, link-local incl. cloud metadata 169.254.169.254,
  multicast, reserved, unspecified, or IPv4-mapped equivalents)
- redirects are followed manually (max 3) and every hop is re-validated
- streamed download with a hard size cap; Content-Type/extension are not
  trusted - the body must start with %PDF
Known residual risk: the hostname is validated and then resolved again by the HTTP
client, so a hostile DNS server could in theory rebind between the two lookups
(DNS rebinding). For a personal local app this is low risk; for a shared deployment
put the app behind an egress proxy/firewall that blocks internal ranges.
Set ALLOW_PRIVATE_URLS=true only for local development against a trusted host.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse, urljoin

import requests

MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
ALLOWED_PORTS = {80, 443}


class UnsafeURLError(ValueError):
    """The URL is malformed or points somewhere we refuse to fetch."""


class FetchError(RuntimeError):
    """The (safe) URL could not be fetched or was not a PDF."""


def _is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified
                or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
                or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10")))


def validate_url(url: str) -> tuple:
    """Returns (parsed_url, [validated_ips]) or raises UnsafeURLError."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise UnsafeURLError("A valid URL is required.")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeURLError("The URL has no hostname.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs containing credentials are not allowed.")
    allow_private = os.environ.get("ALLOW_PRIVATE_URLS", "false").lower() == "true"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS and not allow_private:
        raise UnsafeURLError("Only ports 80 and 443 are allowed.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{parsed.hostname}'.") from exc
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not allow_private and not _is_public(ip):
            raise UnsafeURLError("This URL resolves to a non-public address and was blocked.")
        ips.append(str(ip))
    if not ips:
        raise UnsafeURLError("Could not resolve host.")
    return parsed, ips


def fetch_pdf(url: str, dest_path: str, max_bytes: int) -> int:
    """Downloads a PDF safely to dest_path. Returns bytes written."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parsed, ips = validate_url(current)
        session = requests.Session()
        session.trust_env = os.environ.get("SAFE_FETCH_USE_PROXY", "false").lower() == "true"
        try:
            resp = session.get(current, stream=True, allow_redirects=False,
                               timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                               headers={"User-Agent": "ResearcherAgent/1.1", "Accept": "application/pdf,*/*;q=0.5"})
        except requests.RequestException as exc:
            raise FetchError(f"Could not download the PDF: {type(exc).__name__}") from exc
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            resp.close()
            if not loc:
                raise FetchError("Redirect without a Location header.")
            current = urljoin(current, loc)
            continue
        if resp.status_code >= 400:
            resp.close()
            raise FetchError(f"The server responded with HTTP {resp.status_code}.")
        written = 0
        first = True
        try:
            with open(dest_path, "wb") as f:
                for block in resp.iter_content(65536):
                    if not block:
                        continue
                    if first:
                        if not block.startswith(b"%PDF"):
                            raise FetchError("The URL did not return a PDF file.")
                        first = False
                    written += len(block)
                    if written > max_bytes:
                        raise FetchError(f"The PDF exceeds the maximum size of {max_bytes // (1024*1024)} MB.")
                    f.write(block)
        except (FetchError, requests.RequestException) as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            if isinstance(exc, FetchError):
                raise
            raise FetchError(f"Download interrupted: {type(exc).__name__}") from exc
        finally:
            resp.close()
        if written == 0:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise FetchError("The URL returned an empty response.")
        return written
    raise FetchError("Too many redirects.")
