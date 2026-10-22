"""Client HTTP commun : débit limité, reprises sur 429 et 5xx, secrets masqués dans les logs."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Self

import httpx

USER_AGENT = "newrel/0.1 (+https://github.com/Fragzel/TrucFred)"


class HttpError(Exception):
    """Réponse inattendue. Le message ne contient jamais de secret."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimited(HttpError):
    """Le service impose une attente trop longue pour ce run, ou le quota est épuisé."""


class AuthExpired(Exception):
    """Le refresh token est refusé : il faut une ré-autorisation manuelle."""


def mask(value: str | None) -> None:
    """Demande à GitHub Actions de masquer une valeur dérivée d'un secret (token, en-tête)."""
    if value and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{value}", flush=True)


def json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def ensure_ok(response: httpx.Response, what: str) -> None:
    if not response.is_success:
        raise HttpError(f"{what} : HTTP {response.status_code}", response.status_code)


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "5")))
    except ValueError:
        return 5.0


def _quota_exceeded(response: httpx.Response) -> bool:
    error = json_body(response).get("error")
    return isinstance(error, dict) and error.get("reason") == "QUOTA_EXCEEDED"


class HttpClient:
    def __init__(
        self,
        *,
        requests_per_second: float = 2.0,
        max_retry_after: float = 120.0,
        retries: int = 3,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._max_retry_after = max_retry_after
        self._retries = retries
        self._sleep = sleep
        self._clock = clock
        self._next_slot = 0.0
        self.calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _wait_turn(self) -> None:
        now = self._clock()
        if now < self._next_slot:
            self._sleep(self._next_slot - now)
        self._next_slot = max(now, self._next_slot) + self._interval

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Renvoie la réponse, 4xx compris : c'est à l'appelant de l'interpréter."""
        attempt = 0
        while True:
            self._wait_turn()
            self.calls += 1
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    path = httpx.URL(url).path
                    raise HttpError(f"{method} {path} : {type(exc).__name__}") from exc
                self._sleep(2**attempt)
                attempt += 1
                continue
            if response.status_code == 429:
                if _quota_exceeded(response):
                    # La fenêtre du quota n'est pas documentée : on garde l'indice du serveur.
                    hint = response.headers.get("Retry-After")
                    detail = f", Retry-After : {hint} s" if hint else ", sans Retry-After"
                    raise RateLimited(f"quota épuisé (QUOTA_EXCEEDED{detail})", 429)
                wait = _retry_after(response)
                if wait > self._max_retry_after or attempt >= self._retries:
                    raise RateLimited(
                        f"limite de débit atteinte (attente demandée : {wait:.0f} s)", 429
                    )
                self._sleep(wait)
                attempt += 1
                continue
            if response.status_code >= 500 and attempt < self._retries:
                self._sleep(2**attempt)
                attempt += 1
                continue
            return response
