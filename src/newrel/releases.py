"""Construction de releases.json, le contrat public lu par le site, à partir de l'état."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from newrel import dates, dedup
from newrel.config import Config
from newrel.models import (
    Artist,
    Cover,
    Link,
    LinkState,
    Release,
    ReleasesFile,
    Rules,
    SourceSummary,
    State,
)

PLATFORM_ORDER = {"spotify": 0, "soundcloud": 1}
PRECISION_ORDER = {"day": 0, "month": 1, "year": 2}


def build(state: State, config: Config, *, generated_at: datetime, now: datetime) -> ReleasesFile:
    tz = ZoneInfo(config.timezone)
    cutoff = now.astimezone(tz).date() - timedelta(days=config.window_days)
    releases: list[Release] = []
    aliases: dict[str, str] = {}
    for keys in dedup.cluster(state.links):
        release = _release([(key, state.links[key]) for key in keys], tz)
        if release.sort_date < cutoff:
            continue
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
        sources={
            name: SourceSummary(
                status=source.status,
                message=source.message,
                last_success_at=source.last_success_at,
                followed=len(source.followings),
            )
            for name, source in sorted(state.sources.items())
        },
        aliases=dict(sorted(aliases.items())),
        releases=releases,
    )


def _release(links: list[tuple[str, LinkState]], tz: ZoneInfo) -> Release:
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
    dated = min(
        (link.item for link in ranked),
        key=lambda item: (
            PRECISION_ORDER[item.precision],
            dates.bounds(item.date, item.precision)[0],
        ),
    )
    artists: dict[str, Artist] = {}
    per_platform: dict[str, Link] = {}
    for link in ranked:
        item = link.item
        for artist in item.artists:
            canonical = dedup.artist_id(artist.key)
            artists.setdefault(canonical, Artist(id=canonical, name=artist.name))
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
    return Release(
        id=dedup.release_id(first_key),
        title=primary.title,
        edition=dedup.split_title(primary.title)[1],
        type=primary.type,
        type_inferred=primary.type_inferred,
        artists=list(artists.values()),
        date=dated.date,
        precision=dated.precision,
        sort_date=dates.sort_date(
            dated.date, dated.precision, first.first_seen.astimezone(tz).date(), first.backfill
        ),
        first_seen=first.first_seen,
        backfill=first.backfill,
        tracks=primary.tracks,
        cover=Cover(url=with_cover.cover, platform=with_cover.platform)
        if with_cover and with_cover.cover
        else None,
        links=list(per_platform.values()),
    )
