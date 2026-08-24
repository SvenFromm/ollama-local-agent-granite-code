from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


class InternetTools:
    def __init__(
        self,
        max_bytes: int = 1_000_000,
        allow_private_network: bool = False,
        resolver: Callable[..., Any] = socket.getaddrinfo,
    ) -> None:
        self.max_bytes = max_bytes
        self.allow_private_network = allow_private_network
        self._resolver = resolver

    def _validate_url(self, url: str) -> tuple[bool, str]:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError as exc:
            return False, f"Invalid URL: {exc}"
        if parsed.scheme not in {"http", "https"}:
            return False, "Only HTTP and HTTPS URLs are allowed"
        if not parsed.hostname:
            return False, "URL must contain a hostname"
        if parsed.username or parsed.password:
            return False, "User-info in URLs is not allowed"
        if self.allow_private_network:
            return True, ""
        try:
            infos = self._resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            return False, f"Could not resolve host: {exc}"
        for info in infos:
            address = info[4][0]
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False, f"Private or non-public network target blocked: {address}"
        return True, ""

    def curl_internet(self, url: str, timeout: int = 30) -> dict[str, Any]:
        allowed, reason = self._validate_url(url)
        if not allowed:
            return {"ok": False, "url": url, "error": reason}
        timeout = max(1, min(int(timeout), 60))
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ollama-local-agent-granite-code/1.0"},
        )
        opener = urllib.request.build_opener(_SafeRedirectHandler(self))
        try:
            with opener.open(request, timeout=timeout) as response:
                body_bytes = response.read(self.max_bytes + 1)
                truncated = len(body_bytes) > self.max_bytes
                body_bytes = body_bytes[: self.max_bytes]
                body = body_bytes.decode("utf-8", errors="replace")
                return {
                    "ok": True,
                    "url": response.geturl(),
                    "status": getattr(response, "status", 200),
                    "content_type": response.headers.get("Content-Type"),
                    "truncated": truncated,
                    "body": body,
                }
        except urllib.error.HTTPError as exc:
            return {"ok": False, "url": url, "status": exc.code, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, internet: InternetTools) -> None:
        super().__init__()
        self.internet = internet

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        allowed, reason = self.internet._validate_url(newurl)
        if not allowed:
            raise urllib.error.URLError(f"Redirect blocked: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)
