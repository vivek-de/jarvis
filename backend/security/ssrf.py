"""
backend/security/ssrf.py — SSRF guard for the fetch/browse layer (defined Phase 1,
used from Phase 7).
═══════════════════════════════════════════════════════════════════════════════
Blocks requests to localhost / private / link-local / loopback IPs UNLESS the
host:port is on an explicit allowlist (OptionIQ :3001 and Ollama :11434 by
default). Public internet hosts are allowed. Stdlib-only so it's easy to test.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFError(Exception):
    pass


def _is_private_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        # unresolvable → treat as unsafe
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return True
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
    return False


def check_url(url: str, allowlist: set[str]) -> str:
    """Raise SSRFError if the URL must not be fetched. Returns the url if OK."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"blocked scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SSRFError("no host in URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    hostport = f"{host}:{port}"

    if hostport in allowlist or host in allowlist:
        return url
    if _is_private_ip(host):
        raise SSRFError(f"blocked private/loopback host not on allowlist: {hostport}")
    return url


def is_allowed(url: str, allowlist: set[str]) -> bool:
    try:
        check_url(url, allowlist)
        return True
    except SSRFError:
        return False
