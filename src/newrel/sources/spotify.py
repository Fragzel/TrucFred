"""Source Spotify : abonnements avec le token utilisateur, catalogue avec Client Credentials.

Si le refresh token expire (6 mois), seuls les nouveaux abonnements cessent d'être vus : les
sorties des artistes déjà connus continuent d'arriver via le token d'application.

Le catalogue est limité à environ 100 appels par 24 h en Development Mode. Chaque run dépense
donc un budget fixe, en commençant par les artistes les plus en retard, et ne relit en détail
un artiste que si son nombre total de sorties a augmenté (un seul appel sinon).

Les genres viennent des artistes suivis (/me/following les donne sans appel catalogue) : Spotify
n'en donne pas par album.
"""

from __future__ import annotations

import base64
import itertools
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from newrel import dates, github, styles
from newrel.http import AuthExpired, HttpClient, HttpError, RateLimited, ensure_ok, json_body, mask
from newrel.models import FollowedArtist, ItemArtist, SourceItem
from newrel.sources.base import ArtistCheck, SourceContext, SourceResult, followings_guard

PLATFORM = "spotify"
REQUIRED_ENV = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN")
API_URL = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PAGE_LIMIT = 10  # maximum accepté par GET /artists/{id}/albums depuis 2026
QUOTA_MARGIN = timedelta(minutes=10)  # le run de la veille a étalé ses appels sur une minute
REAUTH_HINT = "ré-autorise Spotify avec « uv run newrel auth spotify »"


class SpotifyApi:
    def __init__(self, http: HttpClient, client_id: str, client_secret: str) -> None:
        self.http = http
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        mask(credentials)
        self._basic = f"Basic {credentials}"
        self._app_token: str | None = None
        self.catalog_calls = 0

    def _token(self, form: dict[str, str]) -> dict[str, Any]:
        response = self.http.request(
            "POST", TOKEN_URL, data=form, headers={"Authorization": self._basic}
        )
        error = json_body(response).get("error")
        if response.status_code == 400 and error == "invalid_grant":
            raise AuthExpired(f"refresh token refusé (invalid_grant) : {REAUTH_HINT}")
        if error == "invalid_client":
            raise HttpError(
                "Client ID ou Client Secret refusé (invalid_client)", response.status_code
            )
        ensure_ok(response, "jeton Spotify")
        payload = response.json()
        mask(payload.get("access_token"))
        mask(payload.get("refresh_token"))
        return payload

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        return self._token(form)

    def refresh_user_token(self, refresh_token: str) -> tuple[str, str | None]:
        """Renvoie l'access token, et le nouveau refresh token si Spotify en a émis un autre."""
        payload = self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        rotated = payload.get("refresh_token")
        return payload["access_token"], rotated if rotated and rotated != refresh_token else None

    def app_token(self, *, renew: bool = False) -> str:
        if self._app_token is None or renew:
            self._app_token = self._token({"grant_type": "client_credentials"})["access_token"]
        return self._app_token

    def get(self, path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.http.request(
            "GET", f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
        ensure_ok(response, f"GET {path}")
        return response.json()

    def followed_artists(self, token: str) -> list[FollowedArtist]:
        artists: dict[str, FollowedArtist] = {}
        params: dict[str, Any] = {"type": "artist", "limit": 50}
        while True:
            page = self.get("/me/following", token, params)["artists"]
            for raw in page.get("items") or []:
                if raw and raw.get("id"):
                    key = f"spotify:artist:{raw['id']}"
                    artist = FollowedArtist(
                        key=key,
                        name=raw.get("name") or "",
                        genres=styles.useful(raw.get("genres") or []),
                    )
                    artists.setdefault(key, artist)
            after = (page.get("cursors") or {}).get("after")
            if not page.get("next") or not after:
                return list(artists.values())
            params = {**params, "after": after}

    def artist_albums(
        self, artist_id: str, groups: str, market: str, offset: int, limit: int = PAGE_LIMIT
    ) -> dict[str, Any]:
        """Un appel catalogue, décompté du quota quotidien."""
        path = f"/artists/{artist_id}/albums"
        params = {"include_groups": groups, "market": market, "limit": limit, "offset": offset}
        self.catalog_calls += 1
        try:
            return self.get(path, self.app_token(), params)
        except HttpError as exc:
            if exc.status_code != 401:
                raise
            self.catalog_calls += 1
            return self.get(path, self.app_token(renew=True), params)  # token d'application expiré


def album_to_item(album: dict[str, Any]) -> SourceItem | None:
    """Album Spotify → sortie normalisée ; None pour une compilation ou une date inexploitable."""
    album_type, tracks = album.get("album_type"), album.get("total_tracks")
    if album_type == "album":
        kind, inferred = "album", False
    elif album_type == "single":
        # L'API range les EP parmi les singles : on les reconnaît au nombre de titres.
        inferred = bool(tracks and tracks >= 4)
        kind = "ep" if inferred else "single"
    else:
        return None
    parsed = dates.normalize(album.get("release_date"), album.get("release_date_precision"))
    if parsed is None:
        return None
    value, precision = parsed
    album_id = album["id"]
    return SourceItem(
        key=f"spotify:album:{album_id}",
        platform=PLATFORM,
        id=album_id,
        url=(album.get("external_urls") or {}).get("spotify")
        or f"https://open.spotify.com/album/{album_id}",
        title=album.get("name") or "",
        type=kind,
        type_inferred=inferred,
        artists=[
            ItemArtist(key=f"spotify:artist:{artist['id']}", name=artist.get("name") or "")
            for artist in album.get("artists") or []
            if artist and artist.get("id")
        ],
        date=value,
        precision=precision,
        tracks=tracks,
        cover=_pick_cover(album.get("images") or []),
        genres=[],  # ceux de l'artiste suffisent
    )


def _pick_cover(images: list[dict[str, Any]]) -> str | None:
    """La plus petite image d'au moins 300 px, sinon la première."""
    usable = [image for image in images if image and image.get("url")]
    large = [image for image in usable if (image.get("width") or 0) >= 300]
    if large:
        return min(large, key=lambda image: image["width"])["url"]
    return usable[0]["url"] if usable else None


def collect(
    ctx: SourceContext,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SourceResult:
    settings = ctx.config.spotify
    result = SourceResult(platform=PLATFORM)
    client = http or HttpClient(
        requests_per_second=settings.requests_per_second,
        max_retry_after=settings.max_retry_after_seconds,
    )
    try:
        api = SpotifyApi(client, ctx.env["SPOTIFY_CLIENT_ID"], ctx.env["SPOTIFY_CLIENT_SECRET"])
        artists = _followings(api, ctx, result)
        if artists:
            _catalog(api, ctx, result, artists, clock)
        _record_window(api, ctx, result)
    finally:
        result.calls = client.calls
        if http is None:
            client.close()
    return result


def _followings(api: SpotifyApi, ctx: SourceContext, result: SourceResult) -> list[FollowedArtist]:
    """Abonnements à vérifier : la liste fraîche, ou la précédente si elle est indisponible."""
    previous = list(ctx.previous_followings)
    try:
        token, rotated = api.refresh_user_token(ctx.env["SPOTIFY_REFRESH_TOKEN"])
        if rotated:
            _store_rotated_token(rotated, ctx, result)
        fetched = api.followed_artists(token)
    except AuthExpired as exc:
        result.degrade("auth_expired", f"{exc} ; abonnements figés à leur dernier état")
        return previous
    except HttpError as exc:
        result.degrade("error", f"abonnements indisponibles ({exc}) : liste précédente utilisée")
        return previous
    problem = followings_guard(
        fetched, ctx.previous_followings, ctx.config.followings_drop_ratio, ctx.accept_drop
    )
    if problem:
        result.degrade("error", problem)
        return previous
    result.followings = fetched
    return fetched


def _store_rotated_token(token: str, ctx: SourceContext, result: SourceResult) -> None:
    pat, repo = ctx.env.get("NEWREL_SECRETS_PAT"), ctx.env.get("GITHUB_REPOSITORY")
    if pat and repo and github.set_secret("SPOTIFY_REFRESH_TOKEN", token, repo=repo, token=pat):
        result.warnings.append("Spotify a émis un nouveau refresh token : secret mis à jour")
        return
    result.warnings.append(
        "Spotify a émis un nouveau refresh token qui n'a pas pu être enregistré"
        " (secret NEWREL_SECRETS_PAT absent) : si l'ancien est invalidé, le prochain run échouera"
    )


def _catalog(
    api: SpotifyApi,
    ctx: SourceContext,
    result: SourceResult,
    artists: list[FollowedArtist],
    clock: Callable[[], float],
) -> None:
    settings = ctx.config.spotify
    if ctx.quota_reset_at and ctx.now < ctx.quota_reset_at:
        result.quota_reset_at, result.pending = ctx.quota_reset_at, len(artists)
        stamp = _local(ctx.quota_reset_at, ctx)
        result.degrade("partial", f"quota épuisé jusqu'au {stamp} : aucun artiste vérifié")
        return
    if (opens := _window_opens(ctx)) and ctx.now < opens:
        # Le quota de la veille court encore : un run manuel ou un cron en avance n'y touche pas.
        result.pending = len(artists)
        result.message = f"quota de 24 h : prochaine vérification possible le {_local(opens, ctx)}"
        return
    try:
        api.app_token()
    except HttpError as exc:
        result.degrade("error", f"jeton d'application indisponible ({exc})")
        return
    queue = sorted(artists, key=lambda artist: _priority(artist, ctx))
    deadline = clock() + settings.time_budget_minutes * 60
    for index, artist in enumerate(queue):
        postponed = len(queue) - index
        if clock() > deadline:
            result.pending = postponed
            result.degrade("partial", f"budget de temps épuisé : {postponed} artiste(s) reportés")
            return
        remaining = settings.daily_catalog_calls - api.catalog_calls
        try:
            check = _check_artist(api, ctx, result, artist, remaining)
        except RateLimited as exc:
            result.pending = postponed
            message = f"{exc} : {postponed} artiste(s) reporté(s)"
            if exc.quota and exc.retry_after is not None:
                result.quota_reset_at = ctx.now + timedelta(seconds=exc.retry_after)
                message += f", reprise après le {_local(result.quota_reset_at, ctx)}"
            result.degrade("partial", message)
            return
        except HttpError as exc:
            if exc.status_code == 404:  # artiste supprimé du catalogue
                result.checked[artist.key] = ArtistCheck()
            else:
                result.degrade("partial", f"{artist.name} non vérifié ({exc})")
            continue
        if check is None:  # budget du jour atteint : c'est le fonctionnement normal
            result.pending = postponed
            return
        result.checked[artist.key] = check


def _window_end(used_at: datetime | None, ctx: SourceContext) -> datetime | None:
    """Fin de la fenêtre de quota ouverte par un run qui a interrogé le catalogue (0 h : aucune)."""
    hours = ctx.config.spotify.quota_window_hours
    if used_at is None or hours <= 0:
        return None
    return used_at + timedelta(hours=hours) + QUOTA_MARGIN


def _window_opens(ctx: SourceContext) -> datetime | None:
    return _window_end(ctx.catalog_used_at, ctx)


def _record_window(api: SpotifyApi, ctx: SourceContext, result: SourceResult) -> None:
    """Retient quand le catalogue redevient interrogeable (affiché sur la page)."""
    result.catalog_used_at = ctx.now if api.catalog_calls else ctx.catalog_used_at
    opens = _window_end(result.catalog_used_at, ctx)
    moments = [moment for moment in (opens, result.quota_reset_at) if moment]
    result.next_check_at = max(moments, default=None)


def _local(moment: datetime, ctx: SourceContext) -> str:
    return moment.astimezone(ZoneInfo(ctx.config.timezone)).strftime("%d/%m à %H:%M")


def _interval_days(artist_key: str, ctx: SourceContext) -> float:
    """Rythme de vérification : un artiste sans sortie depuis un an passe moins souvent."""
    settings = ctx.config.spotify
    latest = ctx.artists[artist_key].latest_release
    if latest is not None and (ctx.now.date() - latest).days > settings.active_within_days:
        return settings.dormant_interval_days
    return settings.active_interval_days


def _priority(artist: FollowedArtist, ctx: SourceContext) -> tuple[int, float, str]:
    """Jamais vérifiés d'abord, puis les plus en retard sur leur rythme."""
    state = ctx.artists.get(artist.key)
    if state is None:
        return (0, 0.0, artist.key)
    elapsed = (ctx.now - state.last_checked_at).total_seconds() / 86_400
    return (1, -elapsed / _interval_days(artist.key, ctx), artist.key)


def _latest(*candidates: date | None) -> date | None:
    return max((day for day in candidates if day is not None), default=None)


def _check_artist(
    api: SpotifyApi,
    ctx: SourceContext,
    result: SourceResult,
    artist: FollowedArtist,
    remaining: int,
) -> ArtistCheck | None:
    """Vérifie un artiste ; None si le budget d'appels restant ne suffit pas."""
    settings = ctx.config.spotify
    state = ctx.artists.get(artist.key)
    detailed_cost = len(settings.groups)
    if (
        state is None
        or state.catalog_total is None
        or state.last_full_at is None
        or ctx.now - state.last_full_at >= timedelta(days=settings.full_check_days)
    ):
        if remaining < detailed_cost:
            return None
        return _full_check(api, ctx, result, artist)
    if remaining < 1 + detailed_cost:
        return None
    total, latest = _catalog_total(api, ctx, artist)
    if total <= state.catalog_total:  # rien d'ajouté : un seul appel dépensé
        latest_release = _latest(state.latest_release, latest)
        return ArtistCheck(catalog_total=total, latest_release=latest_release, full=False)
    return _full_check(api, ctx, result, artist)


def _full_check(
    api: SpotifyApi, ctx: SourceContext, result: SourceResult, artist: FollowedArtist
) -> ArtistCheck:
    baseline = artist.key not in ctx.artists
    items: list[SourceItem] = []
    total = 0
    for group in ctx.config.spotify.groups:
        found, group_total = _fetch_group(api, ctx, result, artist, group, baseline)
        items += found
        total += group_total
    previous = ctx.artists.get(artist.key)
    latest = _latest(
        previous.latest_release if previous else None,
        *(dates.bounds(item.date, item.precision)[0] for item in items),
    )
    return ArtistCheck(items=items, catalog_total=total, latest_release=latest, full=True)


def _catalog_total(
    api: SpotifyApi, ctx: SourceContext, artist: FollowedArtist
) -> tuple[int, date | None]:
    """Nombre total d'albums et de singles, en un seul appel (limit=1)."""
    settings = ctx.config.spotify
    artist_id = artist.key.rsplit(":", 1)[1]
    page = api.artist_albums(artist_id, ",".join(settings.groups), settings.market, 0, limit=1)
    albums = [album for album in page.get("items") or [] if album and album.get("id")]
    first = next((item for item in map(album_to_item, albums) if item), None)
    latest = dates.bounds(first.date, first.precision)[0] if first else None
    return int(page.get("total") or 0), latest


def _fetch_group(
    api: SpotifyApi,
    ctx: SourceContext,
    result: SourceResult,
    artist: FollowedArtist,
    group: str,
    baseline: bool,
) -> tuple[list[SourceItem], int]:
    """Sorties d'un groupe (album ou single) et total du groupe.

    Page suivante seulement s'il peut y avoir du neuf. Premier passage sur un artiste
    (baseline) : une seule page, c'est du catalogue.
    """
    settings = ctx.config.spotify
    artist_id = artist.key.rsplit(":", 1)[1]
    items: list[SourceItem] = []
    total: int | None = None
    offset, warned = 0, False
    for page_number in range(1, settings.max_pages + 1):
        page = api.artist_albums(artist_id, group, settings.market, offset)
        if total is None:
            total = int(page.get("total") or 0)
        albums = [album for album in page.get("items") or [] if album and album.get("id")]
        found = [item for item in map(album_to_item, albums) if item]
        items += found
        last_page = baseline or not page.get("next") or page_number == settings.max_pages
        if last_page or not found:
            break
        offset += len(albums)
        starts = [dates.bounds(item.date, item.precision)[0] for item in found]
        if any(current < following for current, following in itertools.pairwise(starts)):
            # Ordre non documenté par Spotify : s'il n'est plus antichronologique, on lit plus loin.
            if not warned:
                result.warnings.append(
                    f"{artist.name} ({group}) : ordre inattendu, pagination prolongée"
                )
                warned = True
            continue
        oldest_end = dates.bounds(found[-1].date, found[-1].precision)[1]
        all_new = all(item.key not in ctx.known_links for item in found)
        if not (all_new and oldest_end >= ctx.cutoff):
            break
    return items, total or 0
