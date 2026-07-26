"""OAuth2 Authorization-Code-Flow mit PKCE gegen die GGG-API.

Ablauf (docs/ARCHITEKTUR.md §4.1, Parameter siehe docs/api-notes/ggg-api.md):
verifier/challenge/state erzeugen → Browser öffnen → lokaler Callback-Server
fängt den Redirect → state prüfen → code gegen Token tauschen.

"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from poe_view import config

log = logging.getLogger(__name__)

_SUCCESS_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>PoE-VIEW2</title>
<body style="font-family:Segoe UI,sans-serif;background:#1a1712;color:#d6cfbf;
             display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center">
<h1 style="color:#c8a959">Success!</h1>
<p>PoE-VIEW2 received the code. You can close this window now.</p>
</div></body></html>"""

_ERROR_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>PoE-VIEW2</title><body style="font-family:Segoe UI,sans-serif">
<h1>Login failed</h1><p>{reason}</p></body></html>"""


class OAuthError(Exception):
    """Login-Flow fehlgeschlagen (Timeout, State-Mismatch, Token-Tausch)."""


class _CallbackHandler(BaseHTTPRequestHandler):
    """Nimmt genau einen Redirect entgegen und legt die Query-Parameter ab."""

    query: dict[str, list[str]] = {}

    def do_GET(self) -> None:  # noqa: N802 (http.server-API)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        type(self).query = parse_qs(parsed.query)
        ok = "code" in type(self).query
        body = _SUCCESS_HTML if ok else _ERROR_HTML.format(reason="No code received.")
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # Server-Log stumm schalten
        pass


def _make_pkce() -> tuple[str, str]:
    """code_verifier (128 Zeichen, RFC 7636) und code_challenge (S256)."""
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(challenge: str, state: str) -> str:
    params = {
        "client_id": config.CLIENT_ID,
        "response_type": "code",
        "scope": config.SCOPES,
        "state": state,
        "redirect_uri": config.REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.AUTHORIZE_URL}?{urlencode(params)}"


def run_login_flow(timeout_s: float = 300.0) -> dict:
    """Kompletter interaktiver Login. Blockiert (im Worker-Thread aufrufen!).

    Returns:
        Token-Antwort der GGG-API plus ``obtained_at`` (Unix-Zeit) für die
        lokale Ablaufprüfung.
    """
    verifier, challenge = _make_pkce()
    state = f"{secrets.randbits(64):016x}"

    _CallbackHandler.query = {}
    server = HTTPServer(("127.0.0.1", config.REDIRECT_PORT), _CallbackHandler)
    server.timeout = 1.0  # kurze Poll-Intervalle, damit der Timeout greift

    url = build_authorize_url(challenge, state)
    log.info("Öffne Browser für GGG-Login")
    webbrowser.open(url)

    # Requests einzeln abarbeiten, bis der Callback da ist oder Timeout.
    # (Browser fragen oft zusätzlich /favicon.ico an — deshalb eine Schleife.)
    deadline = time.monotonic() + timeout_s
    try:
        while not _CallbackHandler.query:
            if time.monotonic() > deadline:
                raise OAuthError("Timeout: no login within the time window.")
            server.handle_request()
    finally:
        threading.Thread(target=server.server_close, daemon=True).start()

    query = _CallbackHandler.query
    if query.get("state", [""])[0] != state:
        raise OAuthError("State mismatch in callback — login aborted (CSRF protection).")
    if "code" not in query:
        raise OAuthError(f"No authorization code received: {query}")

    return _exchange_code(query["code"][0], verifier)


def _exchange_code(code: str, verifier: str) -> dict:
    """Authorization-Code + Verifier gegen das Access-Token tauschen."""
    data = {
        "client_id": config.CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.REDIRECT_URI,
        "scope": config.SCOPES,
        "code_verifier": verifier,
    }
    headers = {"User-Agent": config.user_agent()}
    resp = httpx.post(config.TOKEN_URL, data=data, headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise OAuthError(f"Token exchange failed (HTTP {resp.status_code}): {resp.text[:300]}")
    token = resp.json()
    token["obtained_at"] = time.time()
    return token
