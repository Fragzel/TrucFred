"""Faux service SoundCloud pour respx : jeton d'application, comptes suivis, sons et playlists.

Les collections sont paginées par next_href et chaque compte suivi expose track_count et
playlist_count, comme l'API officielle.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qs

import httpx
import respx

from newrel.sources.soundcloud import API_URL, TOKEN_URL

API = re.escape(API_URL)


def sc_user(n: int, username: str, *, permalink: str | None = None) -> dict[str, Any]:
    permalink = permalink or f"compte{n}"
    return {
        "urn": f"soundcloud:users:{n}",
        "kind": "user",
        "username": username,
        "permalink": permalink,
        "permalink_url": f"https://soundcloud.com/{permalink}",
        "avatar_url": f"https://i1.sndcdn.com/avatars-{n}-large.jpg",
        "track_count": 0,
        "playlist_count": 0,
    }


def sc_track(
    n: int,
    title: str,
    created_at: str,
    user: dict[str, Any],
    *,
    genre: str | None = None,
    tags: str = "",
) -> dict[str, Any]:
    return {
        "urn": f"soundcloud:tracks:{n}",
        "kind": "track",
        "title": title,
        "permalink_url": f"{user['permalink_url']}/son-{n}",
        "artwork_url": f"https://i1.sndcdn.com/artworks-{n}-large.jpg",
        "created_at": created_at,
        "access": "playable",
        "sharing": "public",
        "genre": genre,
        "tag_list": tags,
        "user": {key: user[key] for key in ("urn", "username", "permalink", "avatar_url")},
    }


def sc_playlist(
    n: int,
    title: str,
    created_at: str,
    user: dict[str, Any],
    *,
    playlist_type: str = "album",
    tracks: tuple[dict[str, Any], ...] = (),
    genre: str | None = None,
) -> dict[str, Any]:
    return {
        "urn": f"soundcloud:playlists:{n}",
        "kind": "playlist",
        "title": title,
        "permalink_url": f"{user['permalink_url']}/sets/set-{n}",
        "artwork_url": f"https://i1.sndcdn.com/artworks-set{n}-large.jpg",
        "created_at": created_at,
        "playlist_type": playlist_type,
        "type": playlist_type,
        "track_count": len(tracks),
        "tracks": list(tracks),
        "genre": genre,
        "tag_list": "",
        "user": {key: user[key] for key in ("urn", "username", "permalink", "avatar_url")},
    }


class FakeSoundCloud:
    def __init__(self, router: respx.MockRouter) -> None:
        self.followed: list[dict[str, Any]] = []
        self.tracks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.playlists: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.followings_status = 200
        self.token_route = router.post(TOKEN_URL).mock(side_effect=self._token)
        self.followings_route = router.get(
            url__regex=rf"{API}/users/(?P<urn>[^/]+)/followings"
        ).mock(side_effect=self._followings)
        self.tracks_route = router.get(url__regex=rf"{API}/users/(?P<urn>[^/]+)/tracks").mock(
            side_effect=self._tracks
        )
        self.playlists_route = router.get(url__regex=rf"{API}/users/(?P<urn>[^/]+)/playlists").mock(
            side_effect=self._playlists
        )
        self.playlist_route = router.get(url__regex=rf"{API}/playlists/(?P<urn>[^/?]+)").mock(
            side_effect=self._playlist
        )

    def follow(self, *users: dict[str, Any]) -> None:
        self.followed.extend(users)

    def upload(self, user: dict[str, Any], *tracks: dict[str, Any]) -> None:
        """Ajoute des sons en tête (les plus récents d'abord) et met à jour le compteur."""
        self.tracks[user["urn"]][:0] = tracks
        user["track_count"] += len(tracks)

    def publish(self, user: dict[str, Any], *playlists: dict[str, Any]) -> None:
        self.playlists[user["urn"]][:0] = playlists
        user["playlist_count"] += len(playlists)

    @property
    def catalog_calls(self) -> int:
        return self.tracks_route.call_count + self.playlists_route.call_count

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert request.headers["Authorization"].startswith("Basic ")
        assert form == {
            "grant_type": "client_credentials"
        }  # identifiants en Basic, pas dans le corps
        return httpx.Response(200, json={"access_token": "sc-token", "expires_in": 3599})

    def _page(self, request: httpx.Request, elements: list[dict[str, Any]]) -> httpx.Response:
        assert request.headers["Authorization"] == "OAuth sc-token"
        params = request.url.params
        limit, offset = int(params.get("limit", "50")), int(params.get("offset", "0"))
        chunk = elements[offset : offset + limit]
        more = offset + limit < len(elements)
        base = str(request.url.copy_with(query=None))
        next_href = f"{base}?limit={limit}&offset={offset + limit}&linked_partitioning=true"
        return httpx.Response(
            200, json={"collection": chunk, "next_href": next_href if more else None}
        )

    def _followings(self, request: httpx.Request, urn: str) -> httpx.Response:
        if self.followings_status != 200:
            return httpx.Response(self.followings_status, json={"error": "unauthorized"})
        return self._page(request, [dict(user) for user in self.followed])

    def _tracks(self, request: httpx.Request, urn: str) -> httpx.Response:
        return self._page(request, self.tracks[urn])

    def _playlists(self, request: httpx.Request, urn: str) -> httpx.Response:
        return self._page(request, self.playlists[urn])

    def _playlist(self, request: httpx.Request, urn: str) -> httpx.Response:
        assert request.url.params["show_tracks"] == "true"
        found = [p for playlists in self.playlists.values() for p in playlists if p["urn"] == urn]
        return httpx.Response(200, json=found[0]) if found else httpx.Response(404)
