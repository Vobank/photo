"""Request guards for a server that lives on the user's machine.

Threats addressed:
* DNS rebinding — a malicious site resolves its domain to 127.0.0.1 and talks to us
  from the victim's browser. Blocked by validating the Host header.
* Cross-site requests from other tabs — blocked by validating Origin on anything
  that changes state and on WebSocket upgrades.
* Other devices on the LAN — only possible when the user binds to a non-loopback
  address, and then only with the access token.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from photo.config import is_loopback_host

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOKEN_COOKIE = "photo_token"  # noqa: S105 — a cookie name, not a secret


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:7860
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class GuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: Iterable[str],
        access_token: str | None,
    ) -> None:
        self.app = app
        self.allowed = {"127.0.0.1", "localhost", "::1", *(h.lower() for h in allowed_hosts)}
        self.token = access_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = _host_only(headers.get("host", ""))
        if host not in self.allowed:
            await self._reject(scope, send, 421, "host_not_allowed")
            return

        origin = headers.get("origin")
        is_ws = scope["type"] == "websocket"
        if (is_ws or scope.get("method") not in _SAFE_METHODS) and origin is not None:
            origin_host = _host_only(urlsplit(origin).netloc)
            if origin_host not in self.allowed:
                await self._reject(scope, send, 403, "origin_not_allowed")
                return

        client = scope.get("client")
        client_host = client[0] if client else ""
        if not is_loopback_host(client_host) and not (self.token and self._token_ok(headers)):
            await self._reject(scope, send, 401, "token_required")
            return

        await self.app(scope, receive, send)

    def _token_ok(self, headers: dict[str, str]) -> bool:
        assert self.token is not None
        supplied = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        else:
            for part in headers.get("cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == TOKEN_COOKIE:
                    supplied = value
        return bool(supplied) and hmac.compare_digest(supplied, self.token)

    @staticmethod
    async def _reject(scope: Scope, send: Send, status: int, code: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": code})
            return
        body = f'{{"error":{{"code":"{code}","message":"Request blocked: {code}"}}}}'.encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })  # fmt: skip
        await send({"type": "http.response.body", "body": body})
