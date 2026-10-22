"""Regroupement des liens qui désignent une même sortie, sur une plateforme ou entre plateformes.

- Artistes : un même nom normalisé sur Spotify et SoundCloud désigne le même artiste, sauf
  homonymie (plusieurs comptes de même nom sur une plateforme) ; aliases.toml tranche à la main.
- Sorties : même artiste, même titre normalisé, même édition, dates à ±7 jours et types
  compatibles. Sur une même plateforme, seuls les jumeaux explicit / clean fusionnent.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from newrel import dates
from newrel.config import Aliases
from newrel.models import LinkState

TOLERANCE = timedelta(days=7)
SHORT_TYPES = frozenset({"single", "ep", "track"})
PLATFORM_ORDER = ("spotify", "soundcloud")
_BRACKETS = re.compile(r"\s*[\(\[]([^\)\]]*)[\)\]]")
_DASH_PREFIX = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+)$")
_DASH_SUFFIX = re.compile(r"\s+[-–—]\s+([^-–—]+)$")
_CREDIT = re.compile(r"^(feat|ft|featuring|with|prod|produced by)\b")
_NOISE = re.compile(
    r"^(free\s*(dl|download)|out now|premiere|clip officiel|audio officiel|lyrics?( video)?"
    r"|visuali[sz]er|official (audio|video|music video|lyric video|visuali[sz]er))$"
)
_EDITION = re.compile(
    r"\b(deluxe|remaster\w*|anniversary|live|remix\w*|sped up|slowed|instrumental\w*"
    r"|acoustic|extended|edition|version)\b"
)
_ARTIST_NOISE = ("official", "officiel", "music", "musique", "vevo")


def _short_id(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:10]}"


def release_id(link_key: str) -> str:
    """Identifiant de sortie dérivé du lien : stable d'un run à l'autre, même sans état."""
    return _short_id("r", link_key)


def artist_id(artist_key: str) -> str:
    return _short_id("a", artist_key)


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def compact(text: str) -> str:
    return re.sub(r"[\W_]+", "", fold(text))


def artist_name_key(name: str) -> str:
    """« The Nora Velasco Official », « noravelascomusic » et « Nora Velasco » → « noravelasco »."""
    words = fold(name).strip()
    words = re.sub(r"^the\s+", "", words)
    words = re.sub(r"\s+-\s+topic$", "", words)
    words = re.sub(r"\b(and|et)\b", " ", words)
    key = compact(words)
    trimmed = True
    while trimmed:
        trimmed = False
        for suffix in _ARTIST_NOISE:
            if key.endswith(suffix) and len(key) - len(suffix) >= 3:
                key, trimmed = key[: -len(suffix)], True
    return key


def split_title(title: str, artist_names: Iterable[str] = ()) -> tuple[str, str | None]:
    """Clé de titre et édition : « Album (Deluxe Edition) » → ("album", "Deluxe Edition").

    Le préfixe « Artiste - » courant sur SoundCloud est retiré quand il nomme un des artistes.
    """
    editions: list[str] = []
    text = title
    names = {artist_name_key(name) for name in artist_names} - {""}
    if (prefix := _DASH_PREFIX.match(text)) and artist_name_key(prefix.group(1)) in names:
        text = prefix.group(2)

    def keep_or_extract(segment: str) -> str:
        folded = fold(segment).strip()
        if _CREDIT.match(folded) or _NOISE.match(folded):
            return " "
        if _EDITION.search(folded):
            editions.append(segment.strip())
            return " "
        return f" {segment} "

    text = _BRACKETS.sub(lambda match: keep_or_extract(match.group(1)), text)
    if suffix := _DASH_SUFFIX.search(text):
        folded = fold(suffix.group(1)).strip()
        if folded in {"single", "ep"} or _CREDIT.match(folded) or _NOISE.match(folded):
            text = text[: suffix.start()]
        elif _EDITION.search(folded):
            editions.append(suffix.group(1).strip())
            text = text[: suffix.start()]
    return compact(text) or compact(title), " · ".join(editions) or None


def _platform(artist_key: str) -> str:
    return artist_key.split(":", 1)[0]


def _preference(artist_key: str) -> tuple[int, str]:
    """Identifiant retenu pour un artiste fusionné : celui de Spotify d'abord (stable)."""
    platform = _platform(artist_key)
    rank = PLATFORM_ORDER.index(platform) if platform in PLATFORM_ORDER else len(PLATFORM_ORDER)
    return rank, artist_key


def canonical_artists(names: Mapping[str, str], aliases: Aliases | None = None) -> dict[str, str]:
    """Identifiant commun aux plateformes pour chaque clé d'artiste (spotify:artist:…, …)."""
    aliases = aliases or Aliases()
    keys = sorted(set(names).union(*aliases.same))
    parent = {key: key for key in keys}
    members = {key: {key} for key in keys}

    def root(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    def join(a: str, b: str) -> None:
        first, second = root(a), root(b)
        if first == second:
            return
        merged = members[first] | members[second]
        if any(pair <= merged for pair in aliases.never):
            return  # homonymes déclarés : jamais réunis
        keep, drop = sorted((first, second), key=_preference)
        parent[drop] = keep
        members[keep] = merged
        del members[drop]

    for group in aliases.same:
        first, *others = sorted(group)
        for other in others:
            join(first, other)
    by_name: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for key, name in sorted(names.items()):
        if name_key := artist_name_key(name):
            by_name[name_key][_platform(key)].append(key)
    for platforms in by_name.values():
        # Fusion automatique seulement entre plateformes, et sans homonyme sur l'une d'elles.
        if len(platforms) < 2 or any(len(same) > 1 for same in platforms.values()):
            continue
        first, *others = (same[0] for same in platforms.values())
        for other in others:
            join(first, other)
    return {key: artist_id(root(key)) for key in keys}


@dataclass(frozen=True)
class _View:
    key: str
    platform: str
    title_key: str
    edition_key: str
    artists: frozenset[str]
    type: str
    tracks: int | None
    date: str
    precision: str
    start: date
    end: date

    @classmethod
    def of(cls, key: str, link: LinkState, canonical: Mapping[str, str]) -> _View:
        item = link.item
        title_key, edition = split_title(item.title, (artist.name for artist in item.artists))
        start, end = dates.bounds(item.date, item.precision)
        return cls(
            key=key,
            platform=item.platform,
            title_key=title_key,
            edition_key=compact(edition or ""),
            artists=frozenset(
                canonical.get(artist.key) or artist_id(artist.key) for artist in item.artists
            ),
            type=item.type,
            tracks=item.tracks,
            date=item.date,
            precision=item.precision,
            start=start,
            end=end,
        )


def _same_release(a: _View, b: _View) -> bool:
    if a.title_key != b.title_key or a.edition_key != b.edition_key or not a.artists & b.artists:
        return False
    if a.platform == b.platform:
        # Jumeaux explicit / clean : même date, même type, même nombre de titres.
        return (a.date, a.type, a.tracks) == (b.date, b.type, b.tracks)
    if a.precision == "year" and b.precision == "year":
        close_tracks = a.tracks is None or b.tracks is None or abs(a.tracks - b.tracks) <= 1
        dates_ok = a.start.year == b.start.year and close_tracks
    else:
        dates_ok = a.start - TOLERANCE <= b.end and b.start - TOLERANCE <= a.end
    # Un album ne fusionne qu'à nombre de titres égal : pas avec son single titre.
    short = a.type in SHORT_TYPES and b.type in SHORT_TYPES
    return dates_ok and (short or (a.tracks is not None and a.tracks == b.tracks))


def cluster(
    links: Mapping[str, LinkState], canonical: Mapping[str, str] | None = None
) -> list[list[str]]:
    """Regroupe les clés de liens qui désignent la même sortie (union-find, déterministe)."""
    views = [_View.of(key, link, canonical or {}) for key, link in sorted(links.items())]
    parent = {view.key: view.key for view in views}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    by_title: dict[str, list[_View]] = defaultdict(list)
    for view in views:
        by_title[view.title_key].append(view)
    for group in by_title.values():
        for index, a in enumerate(group):
            for b in group[index + 1 :]:
                if _same_release(a, b):
                    first, second = sorted((root(a.key), root(b.key)))
                    parent[second] = first
    clusters: dict[str, list[str]] = defaultdict(list)
    for view in views:
        clusters[root(view.key)].append(view.key)
    return list(clusters.values())
