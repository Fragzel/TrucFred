"""Faux service YouTube pour respx : abonnements publics d'une chaîne, chaînes, playlists et
vidéos, lus avec une clé API.

Comme l'API : listes paginées par pageToken, 50 éléments au plus par appel, quota épuisé en 403
(quotaExceeded), abonnements privés en 403 (subscriptionForbidden), playlist UULF… des vidéos
longues à côté de la playlist UU… de toutes les vidéos.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import httpx
import respx

from newrel.sources.youtube import API_URL
from tests.helpers import YT_ENV

API = re.escape(API_URL)


def yt_channel(
    n: int,
    title: str,
    *,
    topics: tuple[str, ...] = ("Music",),
    handle: str | None = None,
    keywords: str = "",
) -> dict[str, Any]:
    channel_id = f"UC{n:022d}"
    return {
        "id": channel_id,
        "snippet": {"title": title, "customUrl": handle or f"@chaine{n}"},
        "contentDetails": {"relatedPlaylists": {"uploads": f"UU{channel_id[2:]}"}},
        "topicDetails": {
            "topicCategories": [f"https://en.wikipedia.org/wiki/{topic}" for topic in topics]
        },
        "brandingSettings": {"channel": {"keywords": keywords}},
    }


def yt_video(
    video_id: str,
    title: str,
    published: str,
    *,
    category: str = "10",
    duration: str = "PT3M30S",
    live: str = "none",
    topics: tuple[str, ...] = ("Music",),
    tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": video_id,
        "snippet": {
            "publishedAt": published,
            "title": title,
            "categoryId": category,
            "liveBroadcastContent": live,
            "tags": list(tags),
            "thumbnails": {
                "default": {"url": f"https://i.ytimg.com/vi/{video_id}/default.jpg"},
                "medium": {"url": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"},
            },
        },
        "contentDetails": {"duration": duration},
        "topicDetails": {
            "topicCategories": [f"https://en.wikipedia.org/wiki/{topic}" for topic in topics]
        },
    }


def _error(status: int, reason: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": status, "errors": [{"reason": reason}], "message": reason}}
    )


class FakeYouTube:
    def __init__(self, router: respx.MockRouter) -> None:
        self.subscribed: list[dict[str, Any]] = []
        self.videos: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.shorts_playlist_missing = False
        self.quota_exceeded = False
        self.subscriptions_private = False
        self.subscribed_hidden = False
        """Liste publique mais vide : les chaînes restent connues de /channels."""
        self.subscriptions_status = 200
        self.subscriptions_route = router.get(f"{API_URL}/subscriptions").mock(
            side_effect=self._subscriptions
        )
        self.channels_route = router.get(f"{API_URL}/channels").mock(side_effect=self._channels)
        self.playlist_route = router.get(f"{API_URL}/playlistItems").mock(
            side_effect=self._playlist
        )
        self.videos_route = router.get(f"{API_URL}/videos").mock(side_effect=self._videos)

    def subscribe(self, *channels: dict[str, Any]) -> None:
        self.subscribed.extend(channels)

    def upload(self, channel: dict[str, Any], *videos: dict[str, Any]) -> None:
        """Ajoute des vidéos en tête (les plus récentes d'abord)."""
        for video in videos:
            video["snippet"]["channelId"] = channel["id"]
        self.videos[channel["id"]][:0] = videos

    @property
    def calls(self) -> int:
        routes = (self.subscriptions_route, self.channels_route, self.playlist_route)
        return sum(route.call_count for route in (*routes, self.videos_route))

    def _guard(self, request: httpx.Request) -> httpx.Response | None:
        assert request.url.params["key"] == YT_ENV["YOUTUBE_API_KEY"]
        assert "Authorization" not in request.headers
        return _error(403, "quotaExceeded") if self.quota_exceeded else None

    def _page(self, request: httpx.Request, elements: list[dict[str, Any]]) -> httpx.Response:
        params = request.url.params
        size = min(int(params.get("maxResults", "5")), 50)
        start = int(params.get("pageToken", "0"))
        chunk = elements[start : start + size]
        payload: dict[str, Any] = {"items": chunk, "pageInfo": {"totalResults": len(elements)}}
        if start + size < len(elements):
            payload["nextPageToken"] = str(start + size)
        return httpx.Response(200, json=payload)

    def _subscriptions(self, request: httpx.Request) -> httpx.Response:
        if problem := self._guard(request):
            return problem
        if self.subscriptions_status != 200:
            return _error(self.subscriptions_status, "backendError")
        if self.subscriptions_private:
            return _error(403, "subscriptionForbidden")
        assert request.url.params["channelId"] == YT_ENV["YOUTUBE_CHANNEL_ID"]
        visible = [] if self.subscribed_hidden else self.subscribed
        items = [
            {"snippet": {"title": c["snippet"]["title"], "resourceId": {"channelId": c["id"]}}}
            for c in sorted(visible, key=lambda c: c["snippet"]["title"].casefold())
        ]
        return self._page(request, items)

    def _channels(self, request: httpx.Request) -> httpx.Response:
        if problem := self._guard(request):
            return problem
        if handle := request.url.params.get("forHandle"):
            found = [c for c in self.subscribed if c["snippet"]["customUrl"] == handle.lower()]
            return httpx.Response(200, json={"items": found})
        ids = request.url.params["id"].split(",")
        assert len(ids) <= 50
        return httpx.Response(200, json={"items": [c for c in self.subscribed if c["id"] in ids]})

    def _playlist(self, request: httpx.Request) -> httpx.Response:
        if problem := self._guard(request):
            return problem
        playlist = request.url.params["playlistId"]
        channel_id = f"UC{playlist[4:] if playlist.startswith('UULF') else playlist[2:]}"
        if playlist.startswith("UULF") and self.shorts_playlist_missing:
            return _error(404, "playlistNotFound")
        videos = self.videos.get(channel_id, [])
        if playlist.startswith("UULF"):
            videos = [v for v in videos if v["contentDetails"]["duration"] not in ("PT30S",)]
        items = [
            {
                "contentDetails": {
                    "videoId": v["id"],
                    "videoPublishedAt": v["snippet"]["publishedAt"],
                }
            }
            for v in videos
        ]
        return self._page(request, items)

    def _videos(self, request: httpx.Request) -> httpx.Response:
        if problem := self._guard(request):
            return problem
        ids = request.url.params["id"].split(",")
        assert len(ids) <= 50
        found = [v for videos in self.videos.values() for v in videos if v["id"] in ids]
        return httpx.Response(200, json={"items": found})
