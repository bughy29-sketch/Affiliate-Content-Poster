"""Client minimal pentru Pinterest API v5, cu retry și backoff."""

from __future__ import annotations

import base64
import logging
import random
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

API_BASE = "https://api.pinterest.com/v5"
TOKEN_URL = f"{API_BASE}/oauth/token"


class PinterestError(RuntimeError):
    """Eroare la apelul API Pinterest."""


class PinterestClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        session: requests.Session | None = None,
        max_attempts: int = 4,
    ) -> None:
        if not client_id or not client_secret or not refresh_token:
            raise ValueError("Credențialele Pinterest sunt incomplete")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._session = session or requests.Session()
        self._access_token: str | None = None
        self._max_attempts = max_attempts

    def _basic_auth(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _fetch_access_token(self) -> str:
        response = self._session.post(
            TOKEN_URL,
            headers={
                "Authorization": self._basic_auth(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise PinterestError(
                f"Refresh token eșuat: {response.status_code} {response.text[:300]}"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise PinterestError("Răspunsul de token nu conține access_token")
        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != self.refresh_token:
            log.warning(
                "Pinterest a returnat un refresh_token nou. Actualizează secretul "
                "PINTEREST_REFRESH_TOKEN, altfel rulările viitoare vor eșua."
            )
        return token

    def _token(self, force: bool = False) -> str:
        if force or not self._access_token:
            self._access_token = self._fetch_access_token()
        return self._access_token

    def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = 0.0
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.0
        if delay <= 0:
            delay = min(60.0, (2 ** attempt) + random.uniform(0, 1))
        delay += random.uniform(0, 1.5)
        log.info("Backoff %.1fs (încercarea %d)", delay, attempt)
        time.sleep(delay)

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        refreshed = False

        for attempt in range(1, self._max_attempts + 1):
            headers = {"Authorization": f"Bearer {self._token()}"}
            try:
                response = self._session.request(
                    method, url, json=json_body, headers=headers, timeout=30
                )
            except requests.RequestException as exc:
                if attempt >= self._max_attempts:
                    raise PinterestError(f"Eroare de rețea: {exc}") from exc
                self._sleep(attempt)
                continue

            if response.status_code in (200, 201):
                return response.json() if response.content else {}

            if response.status_code == 401 and not refreshed:
                refreshed = True
                self._token(force=True)
                continue

            if response.status_code == 403:
                raise PinterestError(
                    "403 Forbidden — verifică scope-urile app-ului "
                    f"(pins:write, boards:read): {response.text[:300]}"
                )

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt >= self._max_attempts:
                    raise PinterestError(f"{response.status_code}: {response.text[:300]}")
                self._sleep(attempt, response.headers.get("Retry-After"))
                continue

            raise PinterestError(f"{response.status_code}: {response.text[:300]}")

        raise PinterestError("Număr maxim de încercări depășit")

    def create_pin(
        self,
        *,
        board_id: str,
        title: str,
        description: str,
        link: str,
        image_url: str,
        alt_text: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "board_id": board_id,
            "title": title,
            "description": description,
            "link": link,
            "media_source": {"source_type": "image_url", "url": image_url},
        }
        if alt_text:
            body["alt_text"] = alt_text
        return self._request("POST", "/pins", json_body=body)
