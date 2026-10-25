"""Source YouTube : les abonnements d'une chaîne, triés pour ne garder que les chaînes
d'artistes, puis leurs derniers clips et audios officiels.

Les abonnements de la chaîne doivent être publics (paramètres de confidentialité de YouTube) :
une simple clé API suffit alors, sans autorisation OAuth ni token qui expire.

Tri de chaque abonnement, dans l'ordre :
1. youtube.toml (« newrel triage youtube ») : artists et ignore tranchent ;
2. une chaîne déjà suivie le reste, pour éviter les va-et-vient d'un run à l'autre ;
3. indices sans appel supplémentaire : chaîne « - Topic » ou VEVO, même nom qu'un artiste suivi
   sur Spotify ou SoundCloud, sujets YouTube sans rapport avec la musique ;
4. sinon, un échantillon des dernières vidéos : part de la catégorie Musique, titres au nom de
   la chaîne, nombre d'artistes différents dans les titres, part de clips et d'audios.
Un label ou une chaîne de promo (titres de plusieurs autres artistes) est suivi comme un
artiste : ses sorties comptent aussi. Une chaîne douteuse est mise de côté jusqu'au tri manuel.

Les logs du dépôt sont publics : ils ne nomment jamais une chaîne écartée ou douteuse.

Quota : 10 000 unités par jour, remises à zéro à minuit (heure du Pacifique). Chaque appel fait
ici coûte 1 unité, soit environ une par chaîne suivie et par run.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from newrel import dates
from newrel.config import YouTubeConfig
from newrel.dedup import artist_name_key, clean_title, fold, split_prefix
from newrel.http import HttpClient, HttpError, RateLimited, json_body, mask
from newrel.models import FollowedArtist, ItemArtist, SourceItem
from newrel.sources.base import ArtistCheck, SourceContext, SourceResult, followings_guard

PLATFORM = "youtube"
REQUIRED_ENV = ("YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID")
API_URL = "https://www.googleapis.com/youtube/v3"
PAGE_SIZE = 50  # maximum de subscriptions, channels et videos par appel
MAX_SUBSCRIPTION_PAGES = 40  # 2 000 abonnements
MUSIC_CATEGORY = "10"
QUOTA_TZ = ZoneInfo("America/Los_Angeles")
PRIVATE_HINT = (
    "abonnements privés : dans les paramètres YouTube (Confidentialité), décoche « Garder tous mes"
    " abonnements privés »"
)
# Sujets « musique » de topicDetails (pages Wikipédia), d'après la liste de l'API.
MUSIC_TOPICS = frozenset(
    {
        "Music",
        "Christian_music",
        "Classical_music",
        "Country_music",
        "Electronic_music",
        "Hip_hop_music",
        "Independent_music",
        "Jazz",
        "Music_of_Asia",
        "Music_of_Latin_America",
        "Pop_music",
        "Reggae",
        "Rhythm_and_blues",
        "Rock_music",
        "Soul_music",
    }
)
# Seuils du tri automatique, sur l'échantillon des dernières vidéos.
NOT_MUSIC_BELOW = 0.3  # part de vidéos en catégorie Musique sous laquelle la chaîne est écartée
ARTIST_FROM = 0.7  # au-delà, chaîne d'artiste ; dès 0,5 si tous ses sujets sont musicaux
ARTIST_WITH_MUSIC_TOPICS_FROM = 0.5
OTHER_ARTISTS_MAX = 2  # au-delà, label ou chaîne de promo : suivie aussi
RELEASES_MIN = 0.2  # moins de clips et d'audios que ça : sessions, lives… douteuse
OWN_TITLES_FROM = 0.5  # titres au nom de la chaîne : artiste, même hors catégorie Musique
LABEL_REASON = "label ou chaîne de promo"

_EXCLUDED = re.compile(
    r"\b(teaser|trailer|bande[- ]annonce|snippet|preview|apercu|extrait|behind the scenes"
    r"|making[- ]of|coulisses|interview|reaction|vlog|unboxing|documentary|documentaire|podcast"
    r"|livestream|karaoke|tutorial|tuto|q\s*&\s*a|concert|tiny desk|full album|album complet"
    r"|episode|ep\.\s?\d+)\b"
)
_COVER = re.compile(r"\bcover\b")
_LIVE = re.compile(
    r"[(\[|]\s*live\b|\s[-–—]\s*live\b|\ben live\b|\blive\s*$"
    r"|\blive\s+(at|from|in|on|@|a|au|aux|session|performance|version|acoustique|acoustic)\b"
)
_MARKERS = re.compile(
    r"\b(official|officiel|officielle|clip|audio|lyrics?|paroles|visuali[sz]er|mv|music video"
    r"|prod|feat|ft)\b"
)
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


# --- API --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Channel:
    id: str
    title: str
    handle: str = ""
    """« @nora », en minuscules ; vide si la chaîne n'en a pas."""
    topics: tuple[str, ...] = ()
    """Pages Wikipédia de topicDetails : « Music », « Hip_hop_music »…"""
    uploads: str | None = None

    @property
    def key(self) -> str:
        return f"youtube:channel:{self.id}"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.id}"


class PrivateSubscriptions(HttpError):
    """La chaîne garde ses abonnements privés : une clé API ne peut pas les lire."""


def _check(response: httpx.Response, what: str) -> None:
    """Erreurs Google : un quota épuisé arrive en 403 (quotaExceeded), pas en 429.

    Le message cite la raison donnée par Google (API_KEY_INVALID, SERVICE_DISABLED…), jamais
    la clé, qui ne voyage que dans les paramètres de la requête.
    """
    if response.is_success:
        return
    error = json_body(response).get("error")
    entries = (
        [
            *(error.get("errors") or []),
            *(error.get("details") or []),
        ]
        if isinstance(error, dict)
        else []
    )
    reasons = {entry.get("reason") for entry in entries if isinstance(entry, dict)} - {None, ""}
    if response.status_code == 403 and "quotaExceeded" in reasons:
        raise RateLimited("quota YouTube épuisé (quotaExceeded)", quota=True)
    if response.status_code == 403 and reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        raise RateLimited("limite de débit YouTube atteinte")
    if response.status_code == 403 and "subscriptionForbidden" in reasons:
        raise PrivateSubscriptions(PRIVATE_HINT, response.status_code)
    detail = f" ({', '.join(sorted(reasons))})" if reasons else ""
    raise HttpError(f"{what} : HTTP {response.status_code}{detail}", response.status_code)


class YouTubeApi:
    def __init__(self, http: HttpClient, api_key: str) -> None:
        self.http = http
        self._key = api_key
        mask(api_key)

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.http.request("GET", f"{API_URL}{path}", params={**params, "key": self._key})
        _check(response, f"GET {path}")
        return response.json()

    def find_channel(self, text: str) -> Channel | None:
        """Chaîne désignée par une adresse youtube.com, un @handle ou un identifiant UC…"""
        if match := re.search(r"\b(UC[\w-]{22})\b", text):
            return self.channels([match.group(1)]).get(match.group(1))
        match = re.search(r"@([\w.-]+)", text)
        handle = match.group(1) if match else text.strip().rstrip("/").rsplit("/", 1)[-1]
        page = self.get(
            "/channels", {"part": "snippet,contentDetails,topicDetails", "forHandle": f"@{handle}"}
        )
        return next((c for c in map(_channel, page.get("items") or []) if c), None)

    def subscriptions(self, channel_id: str) -> list[tuple[str, str]]:
        """(identifiant, nom) de chaque abonnement public de la chaîne, par ordre alphabétique."""
        found: dict[str, str] = {}
        params: dict[str, Any] = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": PAGE_SIZE,
            "order": "alphabetical",
        }
        for _ in range(MAX_SUBSCRIPTION_PAGES):
            page = self.get("/subscriptions", params)
            for item in page.get("items") or []:
                snippet = item.get("snippet") or {}
                channel_id = (snippet.get("resourceId") or {}).get("channelId")
                if channel_id:
                    found.setdefault(channel_id, snippet.get("title") or channel_id)
            if not (token := page.get("nextPageToken")):
                break
            params = {**params, "pageToken": token}
        return list(found.items())

    def subscription_count(self, channel_id: str) -> int:
        page = self.get("/subscriptions", {"part": "id", "channelId": channel_id, "maxResults": 1})
        return int((page.get("pageInfo") or {}).get("totalResults") or 0)

    def channels(self, ids: list[str]) -> dict[str, Channel]:
        """Fiches des chaînes ; une chaîne supprimée est simplement absente."""
        found: dict[str, Channel] = {}
        for chunk in _chunks(ids, PAGE_SIZE):
            page = self.get(
                "/channels",
                {
                    "part": "snippet,contentDetails,topicDetails",
                    "id": ",".join(chunk),
                    "maxResults": PAGE_SIZE,
                },
            )
            for raw in page.get("items") or []:
                if channel := _channel(raw):
                    found[channel.id] = channel
        return found

    def uploads(self, channel: Channel, limit: int) -> list[tuple[str, str | None]]:
        """(vidéo, date de publication) des dernières vidéos longues, les plus récentes d'abord.

        La playlist UULF… (vidéos longues, sans Shorts ni lives) n'est pas documentée : en cas
        d'absence, on se rabat sur la playlist de toutes les vidéos (UU…).
        """
        for playlist in _upload_playlists(channel):
            try:
                page = self.get(
                    "/playlistItems",
                    {"part": "contentDetails", "playlistId": playlist, "maxResults": limit},
                )
            except HttpError as exc:
                if exc.status_code == 404:
                    continue
                raise
            return [
                (details["videoId"], details.get("videoPublishedAt"))
                for details in (
                    item.get("contentDetails") or {} for item in page.get("items") or []
                )
                if details.get("videoId")
            ]
        return []

    def videos(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(list(dict.fromkeys(ids)), PAGE_SIZE):
            page = self.get(
                "/videos",
                {"part": "snippet,contentDetails", "id": ",".join(chunk), "maxResults": PAGE_SIZE},
            )
            for raw in page.get("items") or []:
                if raw.get("id"):
                    found[raw["id"]] = raw
        return found


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[start : start + size] for start in range(0, len(values), size)]


def _upload_playlists(channel: Channel) -> list[str]:
    playlists = [f"UULF{channel.id[2:]}"] if channel.id.startswith("UC") else []
    fallback = channel.uploads or (f"UU{channel.id[2:]}" if channel.id.startswith("UC") else None)
    return [*playlists, *([fallback] if fallback else [])]


def _channel(raw: dict[str, Any]) -> Channel | None:
    if not raw.get("id"):
        return None
    snippet = raw.get("snippet") or {}
    topics = tuple(
        unquote(url.rstrip("/").rsplit("/", 1)[-1])
        for url in (raw.get("topicDetails") or {}).get("topicCategories") or []
        if isinstance(url, str)
    )
    playlists = (raw.get("contentDetails") or {}).get("relatedPlaylists") or {}
    return Channel(
        id=raw["id"],
        title=snippet.get("title") or raw["id"],
        handle=(snippet.get("customUrl") or "").lower(),
        topics=topics,
        uploads=playlists.get("uploads"),
    )


def next_quota_reset(now: datetime) -> datetime:
    """Le quota de l'API YouTube repart à minuit, heure du Pacifique."""
    day = now.astimezone(QUOTA_TZ).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=QUOTA_TZ).astimezone(UTC)


# --- Vidéos -----------------------------------------------------------------------------------


def duration_seconds(value: str | None) -> int | None:
    """Durée ISO 8601 de l'API (« PT3M45S ») en secondes."""
    match = _DURATION.fullmatch(value or "")
    if not match or not value or value == "P":
        return None
    days, hours, minutes, seconds = (int(group or 0) for group in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _same_name(key: str, own: str) -> bool:
    """« lesram » pour la chaîne « LESRAM 310 », « gzaliquidswords… » pour « GZA »."""
    if key == own:
        return True
    shorter = min(len(key), len(own))
    return shorter >= 3 and (key.startswith(own) or own.startswith(key))


def credited_to(channel: Channel, title: str) -> bool:
    """Titre « Artiste - Morceau » dont le préfixe nomme la chaîne (seule ou avec d'autres)."""
    own = artist_name_key(channel.title)
    parts = split_prefix(title)
    return bool(parts) and any(_same_name(artist_name_key(name), own) for name in parts[0])


def is_release(
    video: dict[str, Any], settings: YouTubeConfig, channel: Channel | None = None
) -> bool:
    """Clip ou audio officiel : ni Short, ni live, ni teaser, making-of, interview…"""
    snippet = video.get("snippet") or {}
    if snippet.get("liveBroadcastContent", "none") != "none":
        return False  # live en cours ou première pas encore diffusée
    seconds = duration_seconds((video.get("contentDetails") or {}).get("duration"))
    if seconds is None or not (
        settings.min_duration_seconds <= seconds <= settings.max_duration_minutes * 60
    ):
        return False
    title = fold(snippet.get("title") or "")
    if "#short" in title or _EXCLUDED.search(title) or _LIVE.search(title):
        return False
    # Hors catégorie Musique, il faut une mention explicite (« Clip officiel », « Audio »…) ou
    # un titre « Artiste - Morceau » au nom de la chaîne.
    if snippet.get("categoryId") == MUSIC_CATEGORY or _MARKERS.search(title):
        return True
    return channel is not None and credited_to(channel, snippet.get("title") or "")


def _day(published_at: str | None, tz: ZoneInfo) -> date | None:
    if not published_at:
        return None
    try:
        moment = datetime.fromisoformat(published_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz).date()


def _thumbnail(snippet: dict[str, Any]) -> str | None:
    """Vignette 320 × 180 (« medium ») : en 16:9 sans bandes noires, recadrée en carré."""
    thumbnails = snippet.get("thumbnails") or {}
    for size in ("medium", "high", "default"):
        url = (thumbnails.get(size) or {}).get("url") or ""
        if url.startswith("https://"):
            return url
    return None


def video_to_item(
    video: dict[str, Any], channel: Channel, tz: ZoneInfo, settings: YouTubeConfig
) -> SourceItem | None:
    snippet = video.get("snippet") or {}
    day = _day(snippet.get("publishedAt"), tz)
    if not video.get("id") or day is None or not is_release(video, settings, channel):
        return None
    title = snippet.get("title") or ""
    return SourceItem(
        key=f"youtube:video:{video['id']}",
        platform=PLATFORM,
        id=video["id"],
        url=f"https://www.youtube.com/watch?v={video['id']}",
        title=clean_title(title, [channel.title]),
        type="video",
        artists=[ItemArtist(key=channel.key, name=channel.title)],
        date=day.isoformat(),
        precision="day",
        cover=_thumbnail(snippet),
    )


# --- Tri des abonnements ----------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    follow: bool | None
    """True : chaîne d'artiste suivie ; False : écartée ; None : douteuse, à trier à la main."""
    reason: str
    manual: bool = False
    """Décision prise dans youtube.toml."""


@dataclass
class Sorting:
    channels: list[Channel]
    """Abonnements encore existants, par ordre alphabétique."""
    verdicts: dict[str, Verdict]
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """Dernières vidéos examinées pour les chaînes que les indices ne suffisaient pas à classer."""
    problem: HttpError | None = None
    """Échantillons interrompus (quota, panne) : les chaînes concernées restent douteuses."""

    def followed(self) -> list[Channel]:
        return [channel for channel in self.channels if self.verdicts[channel.id].follow]

    def doubtful(self) -> list[Channel]:
        return [channel for channel in self.channels if self.verdicts[channel.id].follow is None]


def _entries(values: Iterable[str]) -> frozenset[str]:
    return frozenset(value.strip().lower().lstrip("@") for value in values if value.strip())


def _named_by(channel: Channel, entries: frozenset[str]) -> bool:
    return channel.id.lower() in entries or bool(
        channel.handle and channel.handle.lstrip("@") in entries
    )


def topics_label(topics: Iterable[str]) -> str:
    return ", ".join(topic.replace("_", " ") for topic in topics)


def first_look(channel: Channel, peers: frozenset[str]) -> Verdict | None:
    """Indices qui ne coûtent aucun appel ; None quand il faut regarder les vidéos."""
    title = fold(channel.title).strip()
    if title.endswith(" - topic"):
        return Verdict(True, "chaîne « - Topic » générée par YouTube")
    if title.replace(" ", "").endswith("vevo"):
        return Verdict(True, "chaîne VEVO")
    music = [topic for topic in channel.topics if topic in MUSIC_TOPICS]
    peer = artist_name_key(channel.title) in peers
    if channel.topics and not music:
        if peer:
            return None  # même nom qu'un artiste, mais sujets non musicaux : on regarde
        return Verdict(
            False, f"sujets sans rapport avec la musique : {topics_label(channel.topics)}"
        )
    if peer:
        return Verdict(True, "même nom qu'un artiste suivi sur Spotify ou SoundCloud")
    return None


def _named_after(channel: Channel, title: str) -> bool:
    """Titre au nom de la chaîne : « Artiste - Morceau », ou qui commence par son nom."""
    own = artist_name_key(channel.title)
    return credited_to(channel, title) or (len(own) >= 3 and artist_name_key(title).startswith(own))


def other_artists(channel: Channel, videos: list[dict[str, Any]]) -> set[str]:
    """Artistes autres que la chaîne nommés en tête des titres (« Autre - Titre »).

    Le nom de la chaîne, même abrégé ou complété, n'en est pas un, y compris en fin de titre
    (« Titre - Artiste »). Une reprise (« Morceau - Artiste original (cover) ») non plus.
    """
    own = artist_name_key(channel.title)
    others: set[str] = set()
    for video in videos:
        title = (video.get("snippet") or {}).get("title") or ""
        if _COVER.search(fold(title)) or not (parts := split_prefix(title)):
            continue
        credited = {artist_name_key(name) for name in [*parts[0], parts[1]]} - {""}
        if credited and not any(_same_name(key, own) for key in credited):
            others.add(artist_name_key(parts[0][0]))
    return others


def second_look(channel: Channel, videos: list[dict[str, Any]], settings: YouTubeConfig) -> Verdict:
    if not videos:
        return Verdict(None, "aucune vidéo récente à examiner")
    music = sum(
        1 for video in videos if (video.get("snippet") or {}).get("categoryId") == MUSIC_CATEGORY
    )
    share = music / len(videos)
    stats = f"{music}/{len(videos)} vidéos récentes en catégorie Musique"
    music_topics = bool(channel.topics) and all(topic in MUSIC_TOPICS for topic in channel.topics)
    named = sum(
        1
        for video in videos
        if _named_after(channel, (video.get("snippet") or {}).get("title") or "")
    )
    own_titles = named / len(videos) >= OWN_TITLES_FROM
    named_stats = f"{named}/{len(videos)} titres à son nom"
    if share < NOT_MUSIC_BELOW:
        if music_topics and own_titles:
            return Verdict(True, f"{named_stats}, hors catégorie Musique")
        if music_topics:
            return Verdict(None, f"{stats}, mais des sujets musicaux")
        return Verdict(False, stats)
    if len(others := other_artists(channel, videos)) > OTHER_ARTISTS_MAX:
        return Verdict(True, f"{LABEL_REASON} : titres de {len(others)} autres artistes ; {stats}")
    releases = sum(1 for video in videos if is_release(video, settings, channel))
    if releases / len(videos) < RELEASES_MIN:
        if own_titles:
            return Verdict(True, f"{named_stats}, surtout des lives ou des sessions")
        return Verdict(None, f"peu de clips ou d'audios, plutôt des lives ou des teasers ; {stats}")
    if (
        share >= ARTIST_FROM
        or (share >= ARTIST_WITH_MUSIC_TOPICS_FROM and music_topics)
        or own_titles
    ):
        return Verdict(True, stats)
    return Verdict(None, stats)


def recent_videos(
    api: YouTubeApi, channels: list[Channel], limit: int
) -> dict[str, list[dict[str, Any]]]:
    """Dernières vidéos de chaque chaîne, détail compris (2 appels pour 50 vidéos environ).

    Une chaîne illisible est absente du résultat ; un quota épuisé interrompt tout.
    """
    uploads: dict[str, list[str]] = {}
    for channel in channels:
        try:
            uploads[channel.id] = [vid for vid, _ in api.uploads(channel, limit)]
        except RateLimited:
            raise
        except HttpError:
            continue
    details = api.videos(vid for ids in uploads.values() for vid in ids)
    return {
        channel_id: [details[vid] for vid in ids if vid in details]
        for channel_id, ids in uploads.items()
    }


def sort_subscriptions(
    api: YouTubeApi,
    settings: YouTubeConfig,
    *,
    channel_id: str,
    previous: Iterable[str] = (),
    peer_names: Iterable[str] = (),
) -> Sorting:
    """Lit les abonnements et classe chaque chaîne (HttpError si la liste est illisible)."""
    subscribed = api.subscriptions(channel_id)
    found = api.channels([channel_id for channel_id, _ in subscribed])
    channels = [found[channel_id] for channel_id, _ in subscribed if channel_id in found]
    wanted, ignored = _entries(settings.artists), _entries(settings.ignore)
    followed = set(previous)
    peers = frozenset(artist_name_key(name) for name in peer_names) - {""}
    verdicts: dict[str, Verdict] = {}
    pending: list[Channel] = []
    for channel in channels:
        if _named_by(channel, ignored):
            verdicts[channel.id] = Verdict(False, "écartée dans youtube.toml", manual=True)
        elif _named_by(channel, wanted):
            verdicts[channel.id] = Verdict(True, "retenue dans youtube.toml", manual=True)
        elif channel.key in followed:
            verdicts[channel.id] = Verdict(True, "déjà suivie")
        elif verdict := first_look(channel, peers):
            verdicts[channel.id] = verdict
        else:
            pending.append(channel)
    sorting = Sorting(channels=channels, verdicts=verdicts)
    try:
        sorting.samples = recent_videos(api, pending, settings.uploads_limit)
    except HttpError as exc:
        sorting.problem = exc
    for channel in pending:
        if channel.id in sorting.samples:
            verdicts[channel.id] = second_look(channel, sorting.samples[channel.id], settings)
        elif sorting.problem:
            verdicts[channel.id] = Verdict(None, f"vidéos pas encore examinées ({sorting.problem})")
        else:
            verdicts[channel.id] = Verdict(None, "vidéos illisibles pour l'instant")
    return sorting


# --- Collecte ---------------------------------------------------------------------------------


def collect(
    ctx: SourceContext,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SourceResult:
    settings = ctx.config.youtube
    result = SourceResult(platform=PLATFORM)
    if ctx.quota_reset_at and ctx.now < ctx.quota_reset_at:
        result.quota_reset_at = ctx.quota_reset_at
        stamp = ctx.quota_reset_at.astimezone(ZoneInfo(ctx.config.timezone)).strftime(
            "%d/%m à %H:%M"
        )
        result.degrade("partial", f"quota épuisé jusqu'au {stamp} : rien n'a été lu")
        return result
    client = http or HttpClient(
        requests_per_second=settings.requests_per_second,
        max_retry_after=settings.max_retry_after_seconds,
    )
    try:
        api = YouTubeApi(client, ctx.env["YOUTUBE_API_KEY"])
        channels, samples = _followings(api, ctx, result)
        if channels:
            _catalog(api, ctx, result, channels, samples, clock)
    finally:
        result.calls = client.calls
        if http is None:
            client.close()
    return result


def _stopped(result: SourceResult, ctx: SourceContext, exc: HttpError, what: str) -> None:
    if isinstance(exc, RateLimited) and exc.quota:
        result.quota_reset_at = next_quota_reset(ctx.now)
    result.degrade("partial", f"{what} ({exc})")


def _followings(
    api: YouTubeApi, ctx: SourceContext, result: SourceResult
) -> tuple[list[Channel], dict[str, list[dict[str, Any]]]]:
    """Chaînes d'artistes parmi les abonnements, et vidéos déjà lues pendant le tri."""
    previous = [
        Channel(id=artist.key.rsplit(":", 1)[-1], title=artist.name)
        for artist in ctx.previous_followings
    ]
    try:
        sorting = sort_subscriptions(
            api,
            ctx.config.youtube,
            channel_id=ctx.env["YOUTUBE_CHANNEL_ID"],
            previous=(artist.key for artist in ctx.previous_followings),
            peer_names=ctx.peer_names,
        )
    except HttpError as exc:
        if isinstance(exc, RateLimited) and exc.quota:
            _stopped(result, ctx, exc, "rien n'a été lu")
            return [], {}  # le quota se reconstitue seul : inutile d'insister
        result.degrade("error", f"abonnements indisponibles ({exc}) ; liste précédente utilisée")
        return previous, {}
    if sorting.problem:
        _stopped(result, ctx, sorting.problem, "tri interrompu")
    if doubtful := len(sorting.doubtful()):
        result.warnings.append(
            f"YouTube : {doubtful} chaîne(s) à trier, lance « uv run newrel triage youtube »"
        )
    followed = sorting.followed()
    artists = [FollowedArtist(key=channel.key, name=channel.title) for channel in followed]
    ignored = {
        channel.key
        for channel in sorting.channels
        if sorting.verdicts[channel.id].manual and not sorting.verdicts[channel.id].follow
    }
    # Une chaîne écartée à la main n'est pas une baisse suspecte des abonnements.
    reference = tuple(artist for artist in ctx.previous_followings if artist.key not in ignored)
    problem = followings_guard(
        artists, reference, ctx.config.followings_drop_ratio, ctx.accept_drop
    )
    if problem:
        result.degrade("error", problem)
        return previous, {}
    result.followings = artists
    return followed, sorting.samples


def _in_window(published_at: str | None, ctx: SourceContext, tz: ZoneInfo) -> bool:
    day = _day(published_at, tz)
    return day is None or day >= ctx.cutoff


def _catalog(
    api: YouTubeApi,
    ctx: SourceContext,
    result: SourceResult,
    channels: list[Channel],
    samples: dict[str, list[dict[str, Any]]],
    clock: Callable[[], float],
) -> None:
    settings = ctx.config.youtube
    tz = ZoneInfo(ctx.config.timezone)
    never = datetime.min.replace(tzinfo=UTC)

    def priority(channel: Channel) -> tuple[int, datetime, str]:
        state = ctx.artists.get(channel.key)
        return (1, state.last_checked_at, channel.key) if state else (0, never, channel.key)

    queue = sorted(channels, key=priority)
    deadline = clock() + settings.time_budget_minutes * 60
    recent: dict[str, list[str]] = {}
    to_read = [channel for channel in queue if channel.id not in samples]
    for index, channel in enumerate(to_read):
        postponed = len(to_read) - index
        if clock() > deadline:
            result.pending = postponed
            result.degrade("partial", f"budget de temps épuisé : {postponed} chaîne(s) reportée(s)")
            break
        try:
            uploads = api.uploads(channel, settings.uploads_limit)
        except RateLimited as exc:
            result.pending = postponed
            _stopped(result, ctx, exc, f"{postponed} chaîne(s) reportée(s)")
            break
        except HttpError as exc:
            result.degrade("partial", f"{channel.title} non vérifiée ({exc})")
            continue
        recent[channel.id] = [vid for vid, published in uploads if _in_window(published, ctx, tz)]
    try:
        details = api.videos(vid for ids in recent.values() for vid in ids)
    except HttpError as exc:
        _stopped(result, ctx, exc, f"détail des vidéos indisponible : {len(recent)} chaîne(s)")
        result.pending += len(recent)
        recent, details = {}, {}
    for channel in queue:
        if channel.id in samples:
            videos = samples[channel.id]
        elif channel.id in recent:
            videos = [details[vid] for vid in recent[channel.id] if vid in details]
        else:
            continue
        items = [item for video in videos if (item := video_to_item(video, channel, tz, settings))]
        previous = ctx.artists.get(channel.key)
        days = [dates.bounds(item.date, item.precision)[0] for item in items]
        if previous and previous.latest_release:
            days.append(previous.latest_release)
        result.checked[channel.key] = ArtistCheck(
            items=items, latest_release=max(days, default=None)
        )
