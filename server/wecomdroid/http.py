"""HTTP endpoints the phone talks to. Everything requires the bearer token.

    POST /events       {"events": [...]}      phone -> server (deduplicated by event_id)
    POST /heartbeat    {...status...}         every minute
    GET  /commands                            server -> phone
    GET  /files/<id>                          file for a share_file command
"""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .bot import Bot

log = logging.getLogger("wecomdroid")
MAX_BODY = 8 * 1024 * 1024


def make_handler(bot: Bot, prefix: str = "") -> type[BaseHTTPRequestHandler]:
    expected = b"Bearer " + bot.cfg.token.encode()
    prefix = prefix.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        server_version = "wecomdroid"
        sys_version = ""
        timeout = 30

        def log_message(self, *args):
            pass

        def _authorized(self) -> bool:
            return hmac.compare_digest((self.headers.get("Authorization") or "").encode(), expected)

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _route(self) -> str | None:
            path = urlparse(self.path).path
            if not path.startswith(prefix + "/"):
                return None
            return path[len(prefix):]

        def _deny(self) -> None:
            # Same 404 for "wrong token" and "no such path": don't tell scanners anything.
            self._json(404, {"error": "not found"})

        def do_GET(self):
            try:
                route = self._route()
                if route is None or not self._authorized():
                    return self._deny()
                if route == "/commands":
                    return self._json(200, {"commands": bot.commands()})
                if route.startswith("/files/"):
                    data = bot.file(route.rsplit("/", 1)[-1])
                    return self._deny() if data is None else self._send(200, data, "application/octet-stream")
                self._deny()
            except Exception:  # noqa: BLE001
                log.exception("GET failed")
                self._json(500, {"error": "server error"})

        def do_POST(self):
            try:
                route = self._route()
                if route is None or not self._authorized():
                    return self._deny()
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY:
                    return self._json(400, {"error": "bad request"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    return self._json(400, {"error": "bad request"})
                if route == "/events":
                    events = body.get("events")
                    bot.handle_events(events if isinstance(events, list) else [])
                    return self._json(200, {"ok": True})
                if route == "/heartbeat":
                    bot.heartbeat(body)
                    return self._json(200, {"ok": True})
                self._deny()
            except Exception:  # noqa: BLE001
                log.exception("POST failed")
                self._json(500, {"error": "server error"})

    return Handler
