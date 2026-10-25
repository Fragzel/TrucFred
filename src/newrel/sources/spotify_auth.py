"""Autorisation Spotify en local (tous les ~6 mois) : obtient un refresh token et l'enregistre.

Flux Authorization Code avec client secret (pas PKCE, dont le refresh token change à chaque
rafraîchissement). La redirection arrive sur un petit serveur local en 127.0.0.1.
"""

from __future__ import annotations

import html
import http.server
import secrets
import time
import urllib.parse
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from newrel import github
from newrel.config import ask_env
from newrel.http import HttpClient
from newrel.sources.spotify import SpotifyApi

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SCOPE = "user-follow-read"
TIMEOUT_SECONDS = 300
_PAGE = (
    '<!doctype html><html lang="fr"><meta charset="utf-8"><title>newrel</title>'
    '<body style="font-family:system-ui;margin:3rem;font-size:1.2rem">{}</body></html>'
)


def _wait_for_code(port: int, expected_state: str, url: str) -> str:
    outcome: dict[str, str] = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("state", [""])[0] != expected_state:
                outcome["error"] = "paramètre state inattendu"
            elif "error" in query:
                outcome["error"] = query["error"][0]
            else:
                outcome["code"] = query.get("code", [""])[0]
            ok = bool(outcome.get("code"))
            text = (
                "Autorisation reçue : tu peux fermer cet onglet et revenir au terminal."
                if ok
                else f"Autorisation refusée : {html.escape(outcome.get('error', ''))}."
            )
            body = _PAGE.format(text).encode()
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass  # pas de journal des requêtes : l'URL contient le code d'autorisation

    with http.server.HTTPServer(("127.0.0.1", port), Callback) as server:
        server.timeout = 1
        webbrowser.open(url)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if not outcome.get("code"):
        raise SystemExit(f"Autorisation Spotify échouée : {outcome.get('error', 'délai dépassé')}")
    return outcome["code"]


def authorize(
    *, port: int = 8888, use_gh: bool = True, repo: str | None = None, env_file: Path | None = None
) -> int:
    client_id = ask_env("SPOTIFY_CLIENT_ID")
    client_secret = ask_env("SPOTIFY_CLIENT_SECRET", hidden=True)
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_urlsafe(24)
    query = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"
    print(f"Redirect URI déclarée dans le dashboard Spotify : {redirect_uri}")
    print(f"Si le navigateur ne s'ouvre pas, ouvre cette adresse :\n{url}\n")
    code = _wait_for_code(port, state, url)

    with HttpClient(requests_per_second=5) as client:
        api = SpotifyApi(client, client_id, client_secret)
        refresh_token = api.exchange_code(code, redirect_uri)["refresh_token"]
        # Test de rotation : un rafraîchissement, sans jamais représenter l'ancien token
        # (Spotify peut invalider toute la famille de tokens si un ancien est réutilisé).
        access_token, rotated = api.refresh_user_token(refresh_token)
        refresh_token = rotated or refresh_token
        params = {"type": "artist", "limit": 1}
        followed = api.get("/me/following", access_token, params)["artists"].get("total", 0)
    authorized_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    print(f"OK : {followed} artistes suivis visibles par l'application.")
    if rotated:
        print(
            "Attention : Spotify a émis un nouveau refresh token dès le premier rafraîchissement.\n"
            "Ajoute le secret NEWREL_SECRETS_PAT (voir README) pour que le workflow enregistre\n"
            "le token renouvelé à chaque run."
        )
    else:
        print("Rotation : aucun nouveau refresh token émis, le token reste réutilisable.")

    return github.save_settings(
        secrets={
            "SPOTIFY_CLIENT_ID": client_id,
            "SPOTIFY_CLIENT_SECRET": client_secret,
            "SPOTIFY_REFRESH_TOKEN": refresh_token,
        },
        variables={"SPOTIFY_AUTHORIZED_AT": authorized_at},
        use_gh=use_gh,
        repo=repo,
        env_file=env_file,
    )
