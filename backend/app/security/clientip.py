"""The visitor's real IP address behind a cloud host's proxy (public demo only).

X-Forwarded-For is a list the client can start: "fake, real-client, proxy1, ...". Each proxy *appends* the
address it saw, so only the entries added by our own proxies (counted from the right) can be trusted.
Uvicorn's --forwarded-allow-ips=* walks the list and ends at the client-chosen first entry, which would let a
visitor pick a new "IP" per request and slip past the per-IP login rate limit. So we do it ourselves:
- trust the header only when the TCP peer is a private address (the proxy inside the host's network);
- take the entry TRUSTED_PROXY_HOPS places from the right (1 = the one the host's edge proxy wrote);
- fall back to the peer address when anything is missing or malformed.
"""

import ipaddress


def _private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def forwarded_ip(peer: str, forwarded_for: list[str], hops: int) -> str:
    if not _private(peer):
        return peer  # a direct connection, not through the proxy: the header is the client's own words
    entries = [part.strip() for value in forwarded_for for part in value.split(",") if part.strip()]
    if hops < 1 or len(entries) < hops:
        return peer
    candidate = entries[-hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer
