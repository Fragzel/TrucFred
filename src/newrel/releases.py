"""Construction de releases.json, le contrat public lu par le site, à partir de l'état."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from newrel import dates, dedup, styles
from newrel.config import Aliases, Config
from newrel.models import (
    Artist,
    Cover,
    Link,
    LinkState,
    Release,
    ReleasesFile,
    Rules,
    Schedule,
    SourceState,
    SourceSummary,
    State,
)

PLATFORM_ORDER = {"spotify": 0, "soundcloud": 1, "youtube": 2}
PRECISION_ORDER = {"day": 0, "month": 1, "year": 2}


def build(
    state: State,
    config: Config,
    *,
    generated_at: datetime,
    now: datetime,
    artist_aliases: Aliases | None = None,
    repository: str | None = None,
) -> ReleasesFile:
    tz = ZoneInfo(config.timezone)
    cutoff = now.astimezone(tz).date() - timedelta(days=config.window_days)
    # Un son rangé dans un album ou un EP connu est couvert par la carte de l'album.
    shown = {
        key: link
        for key, link in state.links.items()
        if not (link.item.parent and link.item.parent in state.links)
    }
    canonical = dedup.canonical_artists(_artist_names(state), artist_aliases)
    genres = _Genres.of(state, canonical)
    releases: list[Release] = []
    aliases: dict[str, str] = {}
    for keys in dedup.cluster(shown, canonical):
        release = _release(
            [(key, shown[key]) for key in keys], tz, canonical, config.new_max_age_days
        )
        if release.sort_date < cutoff:
            continue
        release.styles, release.genres = styles.pick(
            [
                [genre for key in keys for genre in shown[key].item.genres or []],
                *genres.around(artist.id for artist in release.artists),
            ]
        )
        releases.append(release)
        for key in keys:
            if (old := dedup.release_id(key)) != release.id:
                aliases[old] = release.id
    releases.sort(
        key=lambda release: (release.sort_date, release.first_seen, release.id), reverse=True
    )
    return ReleasesFile(
        generated_at=generated_at,
        timezone=config.timezone,
        window_days=config.window_days,
        rules=Rules(
            new_days=config.new_days,
            new_max_age_days=config.new_max_age_days,
            stale_hours=config.stale_hours,
        ),
        schedule=Schedule(time=config.schedule_time, grace_minutes=config.schedule_grace_minutes),
        repository=repository,
        sources={name: _summary(source, state) for name, source in sorted(state.sources.items())},
        aliases=dict(sorted(aliases.items())),
        releases=releases,
    )


def _artist_names(state: State) -> dict[str, str]:
    """Nom de chaque artiste connu, abonnements compris, pour le rapprochement entre plateformes."""
    names = {
        artist.key: artist.name for link in state.links.values() for artist in link.item.artists
    }
    for source in state.sources.values():
        names.update({artist.key: artist.name for artist in source.followings})
    return names


class _Genres:
    """Genres connus de chaque artiste (identifiant commun aux plateformes) : les siens
    (Spotify, chaîne YouTube) et ceux de ses sorties."""

    def __init__(self) -> None:
        self.own: dict[str, list[str]] = defaultdict(list)
        self.releases: dict[str, list[str]] = defaultdict(list)

    @classmethod
    def of(cls, state: State, canonical: dict[str, str]) -> _Genres:
        def ident(artist_key: str) -> str:
            return canonical.get(artist_key) or dedup.artist_id(artist_key)

        known = cls()
        for source in state.sources.values():
            for artist in source.followings:
                known.own[ident(artist.key)] += artist.genres
        for link in state.links.values():
            for artist in link.item.artists:
                known.releases[ident(artist.key)] += link.item.genres or []
        return known

    def around(self, artist_ids: Iterable[str]) -> tuple[list[str], list[str]]:
        """Genres des artistes d'une sortie, puis ceux de leurs sorties."""
        ids = list(artist_ids)
        return (
            [genre for artist in ids for genre in self.own.get(artist, [])],
            [genre for artist in ids for genre in self.releases.get(artist, [])],
        )


def _summary(source: SourceState, state: State) -> SourceSummary:
    checks = [
        state.artists[artist.key].last_checked_at
        for artist in source.followings
        if artist.key in state.artists
    ]
    return SourceSummary(
        status=source.status,
        message=source.message,
        last_success_at=source.last_success_at,
        followed=len(source.followings),
        unchecked=len(source.followings) - len(checks),
        checked_last_run=source.checked_last_run,
        oldest_check_at=min(checks, default=None),
        quota_reset_at=source.quota_reset_at,
        last_attempt_at=source.last_attempt_at,
        next_check_at=source.next_check_at,
    )


def _release(
    links: list[tuple[str, LinkState]], tz: ZoneInfo, canonical: dict[str, str], max_age_days: int
) -> Release:
    # La sortie garde l'identifiant de son premier lien détecté, et sa « nouveauté ».
    first_key, first = min(links, key=lambda pair: (pair[1].first_seen, dedup.release_id(pair[0])))
    ranked = [
        link
        for _, link in sorted(
            links,
            key=lambda pair: (
                PLATFORM_ORDER.get(pair[1].item.platform, 99),
                pair[1].first_seen,
                pair[0],
            ),
        )
    ]
    primary = ranked[0].item
    # La date de la plateforme principale (Spotify) si elle est au jour près : un son publié
    # la veille sur SoundCloud ne doit pas faire basculer une sortie du vendredi d'une semaine.
    dated = (
        primary
        if primary.precision == "day"
        else min(
            (link.item for link in ranked),
            key=lambda item: (
                PRECISION_ORDER[item.precision],
                dates.bounds(item.date, item.precision)[0],
            ),
        )
    )
    artists: dict[str, Artist] = {}
    per_platform: dict[str, Link] = {}
    for link in ranked:
        item = link.item
        for artist in item.artists:
            artist_id = canonical.get(artist.key) or dedup.artist_id(artist.key)
            artists.setdefault(artist_id, Artist(id=artist_id, name=artist.name))
        per_platform.setdefault(
            item.platform,
            Link(
                platform=item.platform,
                url=item.url,
                type=item.type,
                date=item.date,
                precision=item.precision,
            ),
        )
    with_cover = next((link.item for link in ranked if link.item.cover), None)
    seen_day = first.first_seen.astimezone(tz).date()
    historical = dates.historical(
        dated.date, dated.precision, seen_day, first.backfill, max_age_days
    )
    return Release(
        id=dedup.release_id(first_key),
        title=primary.title,
        edition=dedup.split_title(primary.title, (artist.name for artist in primary.artists))[1],
        type=primary.type,
        type_inferred=primary.type_inferred,
        artists=list(artists.values()),
        date=dated.date,
        precision=dated.precision,
        sort_date=dates.sort_date(dated.date, dated.precision, seen_day, historical),
        first_seen=first.first_seen,
        backfill=historical,
        tracks=primary.tracks,
        cover=Cover(url=with_cover.cover, platform=with_cover.platform)
        if with_cover and with_cover.cover
        else None,
        links=list(per_platform.values()),
    )
