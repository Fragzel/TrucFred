"""Source SoundCloud : API officielle en Client Credentials, sans token utilisateur.

Tes comptes suivis sont publics : /users/{ton_urn}/followings les liste, avec pour chacun le
nombre de sons et de playlists. Un compte dont ces compteurs n'ont pas bougé ne coûte aucun
appel ; sinon on relit ses derniers sons et ses playlists (albums, EP, singles).
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from newrel import dates
from newrel.http import HttpClient, HttpError, RateLimited, ensure_ok, json_body, mask
from newrel.models import FollowedArtist, ItemArtist, ReleaseType, SourceItem
from newrel.sources.base import ArtistCheck, SourceContext, SourceResult, followings_guard

PLATFORM = "soundcloud"
REQUIRED_ENV = ("SOUNDCLOUD_CLIENT_ID", "SOUNDCLOUD_CLIENT_SECRET", "SOUNDCLOUD_USER_URN")
API_URL = "https://api.soundcloud.com"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
MAX_FOLLOWING_PAGES = 25  # 200 comptes par page

log = logging.getLogger(__name__)


class SoundCloudApi:
    def __init__(self, http: HttpClient, client_id: str, client_secret: str) -> None:
        self.http = http
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        mask(credentials)
        self._basic = f"Basic {credentials}"
        self._token: str | None = None

    def token(self) -> str:
        """Un seul jeton par run : SoundCloud en limite l'émission (50 par 12 h et par app)."""
        if self._token is None:
            response = self.http.request(
                "POST",
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": self._basic, "Accept": "application/json"},
            )
            if json_body(response).get("error") == "invalid_client":
                raise HttpError(
                    "Client ID ou Client Secret SoundCloud refusé (invalid_client)",
                    response.status_code,
                )
            ensure_ok(response, "jeton SoundCloud")
            self._token = response.json()["access_token"]
            mask(self._token)
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self.token()}", "Accept": "application/json"}

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> Any:
        url = path_or_url if path_or_url.startswith("https://") else f"{API_URL}{path_or_url}"
        response = self.http.request("GET", url, params=params, headers=self._headers())
        ensure_ok(response, f"GET {httpx.URL(url).path}")
        return response.json()

    def collection(
        self, path: str, params: dict[str, Any], max_pages: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Éléments d'une collection paginée par next_href ; True s'il restait des pages."""
        items: list[dict[str, Any]] = []
        url: str | None = path
        query: dict[str, Any] | None = {**params, "linked_partitioning": "true"}
        for _ in range(max_pages):
            page = self.get(url, query)
            items += _elements(page)
            url, query = _next(page), None
            if not url:
                return items, False
        return items, True

    def resolve_user(self, profile_url: str) -> dict[str, Any]:
        """Profil soundcloud.com → objet utilisateur de l'API (avec son URN)."""
        response = self.http.request(
            "GET", f"{API_URL}/resolve", params={"url": profile_url}, headers=self._headers()
        )
        location = response.headers.get("Location") or json_body(response).get("location")
        if response.is_redirect or location:
            return self.get(location)
        ensure_ok(response, "résolution du profil SoundCloud")
        return response.json()


def _elements(page: Any) -> list[dict[str, Any]]:
    """Les collections arrivent paginées ({collection, next_href}) ou en simple liste."""
    raw = page if isinstance(page, list) else (page or {}).get("collection") or []
    return [element for element in raw if isinstance(element, dict)]


def _next(page: Any) -> str | None:
    return None if isinstance(page, list) else (page or {}).get("next_href")


def _urn(resource: dict[str, Any], kind: str) -> str | None:
    if resource.get("urn"):
        return resource["urn"]
    if resource.get("id"):
        return f"soundcloud:{kind}:{resource['id']}"
    last = (resource.get("uri") or "").rstrip("/").rsplit("/", 1)[-1]
    if last.startswith("soundcloud:"):
        return last
    return f"soundcloud:{kind}:{last}" if last.isdigit() else None


def _day(created_at: str | None, tz: ZoneInfo) -> str | None:
    """« 2019/01/15 15:40:49 +0000 » (format SoundCloud) ou ISO 8601 → jour local."""
    if not created_at:
        return None
    try:
        moment = datetime.strptime(created_at, "%Y/%m/%d %H:%M:%S %z")
    except ValueError:
        try:
            moment = datetime.fromisoformat(created_at)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz).date().isoformat()


def _artwork(url: str | None) -> str | None:
    """Les pochettes SoundCloud arrivent en 100 px (-large) : on demande la variante 300 px."""
    if not url or not url.startswith("https://"):
        return None
    return url.replace("-large.", "-t300x300.")


def _uploader(resource: dict[str, Any]) -> list[ItemArtist]:
    user = resource.get("user") or {}
    key = user.get("urn") or (f"soundcloud:users:{user['id']}" if user.get("id") else None)
    if not key:
        return []
    return [ItemArtist(key=key, name=user.get("username") or user.get("permalink") or key)]


def track_to_item(track: dict[str, Any], tz: ZoneInfo) -> SourceItem | None:
    urn = _urn(track, "tracks")
    day = _day(track.get("created_at"), tz)
    url = track.get("permalink_url") or ""
    if not urn or not day or track.get("access") == "blocked" or not url.startswith("https://"):
        return None
    return SourceItem(
        key=urn,
        platform=PLATFORM,
        id=urn.rsplit(":", 1)[1],
        url=url,
        title=track.get("title") or "",
        type="track",
        artists=_uploader(track),
        date=day,
        precision="day",
        tracks=1,
        cover=_artwork(track.get("artwork_url") or (track.get("user") or {}).get("avatar_url")),
    )


def release_type(value: str | None, tracks: int | None) -> ReleaseType | None:
    """Type d'une playlist ; None pour les playlists ordinaires et les compilations.

    Les valeurs de playlist_type ne sont pas documentées : on reconnaît les plus courantes.
    """
    normalized = (value or "").strip().lower().replace("_", " ")
    if normalized == "album":
        return "album"
    if normalized == "ep":
        return "ep"
    if normalized == "single":
        return "single"
    if normalized in {"ep single", "ep/single"}:
        return "ep" if (tracks or 0) >= 4 else "single"
    return None


def playlist_to_item(playlist: dict[str, Any], tz: ZoneInfo) -> tuple[SourceItem | None, list[str]]:
    """Playlist → sortie (album, EP, single) et URN des sons qu'elle contient."""
    tracks = playlist.get("track_count")
    kind = release_type(playlist.get("playlist_type") or playlist.get("type"), tracks)
    urn = _urn(playlist, "playlists")
    day = _day(playlist.get("created_at"), tz)
    url = playlist.get("permalink_url") or ""
    if kind is None or not urn or not day or not url.startswith("https://"):
        label = playlist.get("playlist_type") or playlist.get("type")
        if kind is None and label and str(label).lower() not in {"playlist", "compilation"}:
            log.info("SoundCloud : type de playlist ignoré : %s", label)
        return None, []
    members = [
        member
        for member in (_urn(track, "tracks") for track in playlist.get("tracks") or [])
        if member
    ]
    cover = _artwork(playlist.get("artwork_url") or (playlist.get("user") or {}).get("avatar_url"))
    item = SourceItem(
        key=urn,
        platform=PLATFORM,
        id=urn.rsplit(":", 1)[1],
        url=url,
        title=playlist.get("title") or "",
        type=kind,
        artists=_uploader(playlist),
        date=day,
        precision="day",
        tracks=tracks,
        cover=cover,
    )
    return item, members


def collect(
    ctx: SourceContext,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SourceResult:
    settings = ctx.config.soundcloud
    result = SourceResult(platform=PLATFORM)
    client = http or HttpClient(
        requests_per_second=settings.requests_per_second,
        max_retry_after=settings.max_retry_after_seconds,
    )
    try:
        api = SoundCloudApi(
            client, ctx.env["SOUNDCLOUD_CLIENT_ID"], ctx.env["SOUNDCLOUD_CLIENT_SECRET"]
        )
        try:
            api.token()
        except HttpError as exc:
            result.degrade("error", f"jeton SoundCloud indisponible ({exc})")
            return result
        accounts, counts = _followings(api, ctx, result)
        if accounts:
            _catalog(api, ctx, result, accounts, counts, clock)
    finally:
        result.calls = client.calls
        if http is None:
            client.close()
    return result


def _followings(
    api: SoundCloudApi, ctx: SourceContext, result: SourceResult
) -> tuple[list[FollowedArtist], dict[str, int]]:
    """Comptes suivis (moins les exclusions) et, pour chacun, sons + playlists publiés."""
    previous = list(ctx.previous_followings)
    urn = ctx.env["SOUNDCLOUD_USER_URN"]
    try:
        users, truncated = api.collection(
            f"/users/{urn}/followings", {"limit": 200}, MAX_FOLLOWING_PAGES
        )
    except HttpError as exc:
        hint = (
            " : l'API refuse peut-être les comptes suivis en Client Credentials"
            if exc.status_code in (401, 403)
            else ""
        )
        result.degrade(
            "error", f"comptes suivis indisponibles ({exc}){hint} ; liste précédente utilisée"
        )
        return previous, {}
    excluded = {value.strip().lower() for value in ctx.config.soundcloud.exclude}
    fetched: list[FollowedArtist] = []
    counts: dict[str, int] = {}
    for user in users:
        key = _urn(user, "users")
        permalink = (user.get("permalink") or "").lower()
        if not key or key in counts or key.lower() in excluded or permalink in excluded:
            continue
        fetched.append(FollowedArtist(key=key, name=user.get("username") or permalink or key))
        counts[key] = int(user.get("track_count") or 0) + int(user.get("playlist_count") or 0)
    if truncated:
        result.warnings.append("SoundCloud : plus de 5 000 comptes suivis, liste tronquée")
    problem = followings_guard(
        fetched, ctx.previous_followings, ctx.config.followings_drop_ratio, ctx.accept_drop
    )
    if problem:
        result.degrade("error", problem)
        return previous, {}
    result.followings = fetched
    return fetched, counts


def _catalog(
    api: SoundCloudApi,
    ctx: SourceContext,
    result: SourceResult,
    accounts: list[FollowedArtist],
    counts: dict[str, int],
    clock: Callable[[], float],
) -> None:
    settings = ctx.config.soundcloud
    never = datetime.min.replace(tzinfo=UTC)

    def priority(account: FollowedArtist) -> tuple[int, datetime, str]:
        state = ctx.artists.get(account.key)
        return (1, state.last_checked_at, account.key) if state else (0, never, account.key)

    queue = sorted(accounts, key=priority)
    deadline = clock() + settings.time_budget_minutes * 60
    for index, account in enumerate(queue):
        postponed = len(queue) - index
        if clock() > deadline:
            result.pending = postponed
            result.degrade("partial", f"budget de temps épuisé : {postponed} compte(s) reportés")
            return
        state = ctx.artists.get(account.key)
        count = counts.get(account.key)
        recently_read = (
            state is not None
            and state.last_full_at is not None
            and ctx.now - state.last_full_at < timedelta(days=settings.full_check_days)
        )
        if (
            recently_read
            and count is not None
            and state.catalog_total is not None
            and count <= state.catalog_total
        ):
            # Ni son ni playlist ajoutés depuis le dernier passage : aucun appel.
            result.checked[account.key] = ArtistCheck(
                catalog_total=count, latest_release=state.latest_release, full=False
            )
            continue
        try:
            check = _full_check(api, ctx, account)
        except RateLimited as exc:
            result.pending = postponed
            result.degrade("partial", f"{exc} : {postponed} compte(s) reporté(s)")
            return
        except HttpError as exc:
            if exc.status_code == 404:  # compte supprimé
                result.checked[account.key] = ArtistCheck()
            else:
                result.degrade("partial", f"{account.name} non vérifié ({exc})")
            continue
        check.catalog_total = count
        result.checked[account.key] = check


def _full_check(api: SoundCloudApi, ctx: SourceContext, account: FollowedArtist) -> ArtistCheck:
    settings = ctx.config.soundcloud
    tz = ZoneInfo(ctx.config.timezone)
    tracks = _recent_tracks(api, ctx, account, tz)
    playlists = api.get(
        f"/users/{account.key}/playlists",
        {"limit": settings.playlists_limit, "linked_partitioning": "true", "show_tracks": "true"},
    )
    items: list[SourceItem] = []
    parents: dict[str, str] = {}
    for playlist in _elements(playlists):
        item, members = playlist_to_item(playlist, tz)
        if item:
            items.append(item)
            parents.update(dict.fromkeys(members, item.key))
    for track in tracks:
        parent = parents.get(track.key)
        items.append(track.model_copy(update={"parent": parent}) if parent else track)
    previous = ctx.artists.get(account.key)
    latest = _latest(
        previous.latest_release if previous else None,
        *(dates.bounds(item.date, item.precision)[0] for item in items),
    )
    return ArtistCheck(items=items, latest_release=latest, full=True)


def _recent_tracks(
    api: SoundCloudApi, ctx: SourceContext, account: FollowedArtist, tz: ZoneInfo
) -> list[SourceItem]:
    """Derniers sons (du plus récent au plus ancien) ; page suivante seulement s'il peut y avoir
    du neuf. Premier passage sur un compte (baseline) : une seule page."""
    settings = ctx.config.soundcloud
    baseline = account.key not in ctx.artists
    url: str | None = f"/users/{account.key}/tracks"
    query: dict[str, Any] | None = {
        "limit": settings.tracks_limit,
        "linked_partitioning": "true",
        "access": "playable,preview",
    }
    items: list[SourceItem] = []
    for _ in range(settings.max_pages):
        page = api.get(url, query)
        found = [item for item in (track_to_item(t, tz) for t in _elements(page)) if item]
        items += found
        url, query = _next(page), None
        if baseline or not url or not found:
            break
        oldest_end = dates.bounds(found[-1].date, found[-1].precision)[1]
        if not (
            all(item.key not in ctx.known_links for item in found) and oldest_end >= ctx.cutoff
        ):
            break
    return items


def _latest(*days: date | None) -> date | None:
    return max((day for day in days if day is not None), default=None)
