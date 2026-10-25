"""État persistant entre deux runs (state.json) : intégration des résultats, baseline, élagage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from newrel import dates, protect
from newrel.config import Config
from newrel.models import ArtistState, LinkState, SourceItem, SourceState, State
from newrel.sources.base import SourceContext, SourceResult


@dataclass
class ApplyStats:
    new_links: int = 0
    new_releases: list[SourceItem] = field(default_factory=list)
    """Nouveautés hors catalogue (backfill exclu)."""
    removed_artists: int = 0


def load_state(path: Path, key: bytes | None = None) -> State | None:
    """None si le fichier n'existe pas ; ValueError s'il est illisible, ou chiffré sans la clé."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if (sealed := protect.envelope(text)) is not None:
        if key is None:
            raise protect.CryptoError("fichier chiffré, secret STATE_KEY absent")
        text = protect.unseal(sealed, key)
    return State.model_validate_json(text)


def save_state(state: State, path: Path, key: bytes | None = None) -> None:
    """Chiffré avec STATE_KEY quand il est configuré : la branche data est publique."""
    state.sources = dict(sorted(state.sources.items()))
    state.artists = dict(sorted(state.artists.items()))
    state.links = dict(sorted(state.links.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = state.model_dump_json(indent=2) + "\n"
    path.write_text(protect.seal(text, key) if key else text, encoding="utf-8")


def context_for(
    state: State,
    platform: str,
    *,
    config: Config,
    env: Mapping[str, str],
    now: datetime,
    cutoff: date,
    accept_drop: bool = False,
) -> SourceContext:
    prefix = f"{platform}:"
    source = state.sources.get(platform, SourceState())
    return SourceContext(
        config=config,
        env=env,
        now=now,
        cutoff=cutoff,
        known_links=frozenset(key for key in state.links if key.startswith(prefix)),
        artists={key: artist for key, artist in state.artists.items() if key.startswith(prefix)},
        previous_followings=tuple(source.followings),
        quota_reset_at=source.quota_reset_at,
        # État d'avant le 25/10 : le dernier run qui a vérifié des artistes a ouvert la fenêtre.
        catalog_used_at=source.catalog_used_at
        or (source.last_attempt_at if source.checked_last_run else None),
        peer_names=frozenset(
            artist.name
            for name, other in state.sources.items()
            if name != platform
            for artist in other.followings
        ),
        stale_artists=frozenset(
            artist_key
            for key, link in state.links.items()
            if key.startswith(prefix) and link.item.genres is None
            for artist_key in link.via
        ),
        accept_drop=accept_drop,
    )


def apply_result(
    state: State,
    result: SourceResult,
    *,
    now: datetime,
    cutoff: date,
    today: date | None = None,
    max_age_days: int = 14,
) -> ApplyStats:
    """Intègre le résultat d'une source. Ce qui n'a pas été revérifié est conservé tel quel.

    backfill marque un lien trouvé au premier passage sur son artiste ; releases.py décide
    ensuite s'il est du catalogue ou une nouveauté récente (dates.historical).
    """
    today = today or now.date()
    stats = ApplyStats()
    prefix = f"{result.platform}:"
    source = state.sources.setdefault(result.platform, SourceState())
    source.status, source.message = result.status, result.message
    source.last_attempt_at = now
    if result.status in ("ok", "partial"):
        source.consecutive_failures = 0
    else:
        source.consecutive_failures += 1
    if result.status == "ok" or result.checked:
        source.last_success_at = now
    source.quota_reset_at = result.quota_reset_at
    source.checked_last_run = len(result.checked)
    source.catalog_used_at = result.catalog_used_at or source.catalog_used_at
    source.next_check_at = result.next_check_at

    if result.followings is not None:
        followed = {artist.key for artist in result.followings}
        for key in [k for k in state.artists if k.startswith(prefix) and k not in followed]:
            del state.artists[key]
            stats.removed_artists += 1
        for link_key, link in list(state.links.items()):
            link.via = [k for k in link.via if not k.startswith(prefix) or k in followed]
            if not link.via:
                del state.links[link_key]
        source.followings = list(result.followings)
        source.followings_at = now

    names = {artist.key: artist.name for artist in source.followings}
    ungenred = [link for key, link in state.links.items() if key.startswith(prefix)]
    ungenred = [link for link in ungenred if link.item.genres is None]
    for artist_key, check in result.checked.items():
        if check.full:
            # Ce qu'une lecture complète ne revoit pas ne sera pas relu : genres inconnus.
            for link in ungenred:
                if artist_key in link.via:
                    link.item.genres = []
        known = state.artists.get(artist_key)
        for item in check.items:
            if dates.bounds(item.date, item.precision)[1] < cutoff:
                continue  # hors fenêtre : on ne le stocke pas
            link = state.links.get(item.key)
            if link is None:
                backfill = known is None
                state.links[item.key] = LinkState(
                    item=item, first_seen=now, last_seen=now, backfill=backfill, via=[artist_key]
                )
                stats.new_links += 1
                if not dates.historical(item.date, item.precision, today, backfill, max_age_days):
                    stats.new_releases.append(item)
            else:
                link.item, link.last_seen = item, now
                if artist_key not in link.via:
                    link.via.append(artist_key)
        state.artists[artist_key] = ArtistState(
            name=names.get(artist_key) or (known.name if known else artist_key),
            baseline_at=known.baseline_at if known else now,
            last_checked_at=now,
            catalog_total=check.catalog_total,
            latest_release=check.latest_release,
            last_full_at=now if check.full else (known.last_full_at if known else None),
        )
    return stats


def prune(state: State, cutoff: date) -> int:
    """Oublie les liens dont la période est entièrement sortie de la fenêtre.

    On élague sur la fin de période (et non sur la date de tri) : une sortie datée à l'année
    reste connue tant qu'elle pourrait encore être renvoyée par l'API, sinon elle reviendrait
    comme une nouveauté.
    """
    expired = [
        key
        for key, link in state.links.items()
        if dates.bounds(link.item.date, link.item.precision)[1] < cutoff
    ]
    for key in expired:
        del state.links[key]
    return len(expired)
