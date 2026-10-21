"""Regroupement des liens qui désignent une même sortie.

Pour l'instant : les jumeaux explicit / clean d'une même plateforme. Les règles entre
plateformes (dates à ±7 jours, types compatibles) servent dès l'arrivée de SoundCloud.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from newrel import dates
from newrel.models import LinkState

TOLERANCE = timedelta(days=7)
SHORT_TYPES = frozenset({"single", "ep", "track"})
_BRACKETS = re.compile(r"\s*[\(\[]([^\)\]]*)[\)\]]")
_DASH_SUFFIX = re.compile(r"\s+[-–—]\s+([^-–—]+)$")
_CREDIT = re.compile(r"^(feat|ft|featuring|with|prod|produced by)\b")
_EDITION = re.compile(
    r"\b(deluxe|remaster\w*|anniversary|live|remix\w*|sped up|slowed|instrumental\w*"
    r"|acoustic|extended|edition|version)\b"
)


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


def split_title(title: str) -> tuple[str, str | None]:
    """Clé de titre et édition : « Album (Deluxe Edition) » → ("album", "Deluxe Edition")."""
    editions: list[str] = []

    def keep_or_extract(segment: str) -> str:
        folded = fold(segment).strip()
        if _CREDIT.match(folded):
            return " "
        if _EDITION.search(folded):
            editions.append(segment.strip())
            return " "
        return f" {segment} "

    text = _BRACKETS.sub(lambda match: keep_or_extract(match.group(1)), title)
    if suffix := _DASH_SUFFIX.search(text):
        folded = fold(suffix.group(1)).strip()
        if folded in {"single", "ep"} or _CREDIT.match(folded):
            text = text[: suffix.start()]
        elif _EDITION.search(folded):
            editions.append(suffix.group(1).strip())
            text = text[: suffix.start()]
    return compact(text) or compact(title), " · ".join(editions) or None


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
    def of(cls, key: str, link: LinkState) -> _View:
        item = link.item
        title_key, edition = split_title(item.title)
        start, end = dates.bounds(item.date, item.precision)
        return cls(
            key=key,
            platform=item.platform,
            title_key=title_key,
            edition_key=compact(edition or ""),
            artists=frozenset(artist_id(artist.key) for artist in item.artists),
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


def cluster(links: Mapping[str, LinkState]) -> list[list[str]]:
    """Regroupe les clés de liens qui désignent la même sortie (union-find, déterministe)."""
    views = [_View.of(key, link) for key, link in sorted(links.items())]
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
