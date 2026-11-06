#!/usr/bin/env python3
"""Obține un refresh token Pinterest prin fluxul OAuth2 authorization code.

Rulează local, niciodată în CI. Necesită un app Pinterest cu redirect URI
`http://localhost:8080/callback`.

Exemplu:
    python scripts/get_refresh_token.py \
        --client-id "$PINTEREST_CLIENT_ID" \
        --client-secret "$PINTEREST_CLIENT_SECRET"
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import secrets
import socketserver
import sys
import urllib.parse
import webbrowser

import requests

AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
SCOPES = "pins:write,boards:read"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 (nume impus de BaseHTTPRequestHandler)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        type(self).code = (params.get("code") or [None])[0]
        type(self).state = (params.get("state") or [None])[0]
        type(self).error = (params.get("error") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Autorizare primită. Poți închide fereastra.".encode("utf-8"))

    def log_message(self, *args) -> None:  # silențios
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--redirect-uri", default="http://localhost:8080/callback")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    expected_state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": args.client_id,
            "redirect_uri": args.redirect_uri,
            "scope": SCOPES,
            "state": expected_state,
        }
    )
    authorize_url = f"{AUTH_URL}?{query}"

    with socketserver.TCPServer(("127.0.0.1", args.port), _CallbackHandler) as server:
        print("Deschide manual dacă browserul nu pornește:\n" + authorize_url)
        webbrowser.open(authorize_url)
        print("Aștept callback-ul OAuth pe", args.redirect_uri, "...")
        server.handle_request()

    if _CallbackHandler.error:
        print(f"Eroare OAuth: {_CallbackHandler.error}", file=sys.stderr)
        return 1
    if not _CallbackHandler.code:
        print("Nu am primit codul de autorizare.", file=sys.stderr)
        return 1
    if _CallbackHandler.state != expected_state:
        print("State OAuth invalid — posibil atac CSRF.", file=sys.stderr)
        return 1

    basic = base64.b64encode(
        f"{args.client_id}:{args.client_secret}".encode()
    ).decode()
    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": _CallbackHandler.code,
            "redirect_uri": args.redirect_uri,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        print(
            f"Schimbul de token a eșuat: {response.status_code} {response.text}",
            file=sys.stderr,
        )
        return 1

    payload = response.json()
    print(json.dumps(payload, indent=2))
    print("\nSalvează refresh_token în GitHub Secrets ca PINTEREST_REFRESH_TOKEN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
