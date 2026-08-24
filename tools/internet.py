from __future__ import annotations
import urllib.error
import urllib.request
from typing import Any

class InternetTools:
    def curl_internet(self, url: str, timeout: int = 30) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "Only HTTP/HTTPS URLs are allowed"}
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 GraniteLocalAgent/2.0"})
        try:
            with urllib.request.urlopen(request, timeout=min(max(int(timeout), 1), 60)) as response:
                body = response.read(1_000_000).decode("utf-8", errors="replace")
                return {"ok": True, "url": url, "status": response.status,
                        "content_type": response.headers.get("Content-Type"), "body": body}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "url": url, "status": exc.code, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
