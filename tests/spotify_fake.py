"""Faux service Spotify pour respx : abonnements paginés, albums par artiste et par groupe.

Reproduit les contraintes 2026 utiles aux tests : limit ≤ 10 sur les albums, un seul groupe
par appel, token utilisateur pour /me/following et token d'application pour le catalogue.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qs

import httpx
import respx

from newrel.sources.spotify import API_URL, TOKEN_URL


def album(
    album_id: str,
    name: str,
    release_date: str,
    *,
    album_type: str = "single",
    tracks: int = 1,
    precision: str = "day",
    artists: tuple[tuple[str, str], ...] = (("A1", "Artiste Un"),),
) -> dict[str, Any]:
    return {
        "album_type": album_type,
        "total_tracks": tracks,
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
        "href": f"{API_URL}/albums/{album_id}",
        "id": album_id,
        "images": [
            {"url": f"https://i.scdn.co/image/{album_id}-640", "height": 640, "width": 640},
            {"url": f"https://i.scdn.co/image/{album_id}-300", "height": 300, "width": 300},
            {"url": f"https://i.scdn.co/image/{album_id}-64", "height": 64, "width": 64},
        ],
        "name": name,
        "release_date": release_date,
        "release_date_precision": precision,
        "type": "album",
        "uri": f"spotify:album:{album_id}",
        "artists": [
            {
                "external_urls": {"spotify": f"https://open.spotify.com/artist/{artist_id}"},
                "href": f"{API_URL}/artists/{artist_id}",
                "id": artist_id,
                "name": artist_name,
                "type": "artist",
                "uri": f"spotify:artist:{artist_id}",
            }
            for artist_id, artist_name in artists
        ],
    }


class FakeSpotify:
    def __init__(self, router: respx.MockRouter) -> None:
        self.followed: list[tuple[str, str]] = []
        self.albums: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.refresh_error: str | None = None  # "invalid_grant" pour simuler l'expiration
        self.tokens_down = False
        self.rotate = False
        self.failing_artists: set[str] = set()
        self.rate_limited_artists: set[str] = set()
        self.quota: int | None = None  # appels catalogue acceptés avant QUOTA_EXCEEDED
        self.catalog_calls = 0
        self.token_route = router.post(TOKEN_URL).mock(side_effect=self._token)
        self.following_route = router.get(f"{API_URL}/me/following").mock(
            side_effect=self._following
        )
        self.albums_route = router.get(
            url__regex=rf"{re.escape(API_URL)}/artists/(?P<artist_id>[^/]+)/albums"
        ).mock(side_effect=self._albums)

    def follow(self, *artists: tuple[str, str]) -> None:
        self.followed.extend(artists)

    def unfollow(self, artist_id: str) -> None:
        self.followed = [artist for artist in self.followed if artist[0] != artist_id]

    def publish(self, artist_id: str, group: str, *albums: dict[str, Any]) -> None:
        """Ajoute des albums en tête de liste (les plus récents d'abord, comme l'API)."""
        self.albums[(artist_id, group)][:0] = albums

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.tokens_down:
            return httpx.Response(503)
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        grant = form.get("grant_type")
        if grant == "refresh_token":
            if self.refresh_error:
                return httpx.Response(400, json={"error": self.refresh_error})
            payload = {"access_token": "user-token", "token_type": "Bearer", "expires_in": 3600}
            if self.rotate:
                payload["refresh_token"] = "rotated-refresh-token"
            return httpx.Response(200, json=payload)
        if grant == "client_credentials":
            return httpx.Response(200, json={"access_token": "app-token", "expires_in": 3600})
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _following(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer user-token"
        params = request.url.params
        assert params["type"] == "artist"
        limit = int(params.get("limit", "20"))
        assert limit <= 50
        ids = [artist_id for artist_id, _ in self.followed]
        start = ids.index(params["after"]) + 1 if "after" in params else 0
        chunk = self.followed[start : start + limit]
        more = start + limit < len(self.followed)
        items = [
            {"id": artist_id, "name": name, "type": "artist", "uri": f"spotify:artist:{artist_id}"}
            for artist_id, name in chunk
        ]
        page = {
            "href": str(request.url),
            "items": items,
            "limit": limit,
            "next": f"{API_URL}/me/following?type=artist&after={chunk[-1][0]}" if more else None,
            "cursors": {"after": chunk[-1][0] if more else None},
            "total": len(self.followed),
        }
        return httpx.Response(200, json={"artists": page})

    def _albums(self, request: httpx.Request, artist_id: str) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer app-token"
        params = request.url.params
        group, limit = params["include_groups"], int(params["limit"])
        offset = int(params.get("offset", "0"))
        groups = group.split(",")
        # Plusieurs groupes à la fois : seulement pour lire le total (limit=1), comme newrel.
        assert (len(groups) == 1 or limit == 1) and limit <= 10 and params["market"] == "FR"
        self.catalog_calls += 1
        if self.quota is not None and self.catalog_calls > self.quota:
            body = {
                "error": {"status": 429, "message": "Too many requests", "reason": "QUOTA_EXCEEDED"}
            }
            return httpx.Response(429, headers={"Retry-After": "86111"}, json=body)
        if artist_id in self.failing_artists:
            return httpx.Response(503)
        if artist_id in self.rate_limited_artists:
            return httpx.Response(429, headers={"Retry-After": "900"})
        albums = [album for name in groups for album in self.albums.get((artist_id, name), [])]
        more = offset + limit < len(albums)
        page = {
            "href": str(request.url),
            "items": albums[offset : offset + limit],
            "limit": limit,
            "offset": offset,
            "next": f"{API_URL}/artists/{artist_id}/albums?offset={offset + limit}"
            if more
            else None,
            "previous": None,
            "total": len(albums),
        }
        return httpx.Response(200, json=page)
