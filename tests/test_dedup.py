from datetime import UTC, datetime

import pytest

from newrel.dedup import cluster, release_id, split_title
from newrel.models import ItemArtist, LinkState, SourceItem

SEEN = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    ("title", "key", "edition"),
    [
        ("Lumières froides", "lumieresfroides", None),
        ("Song (feat. Someone)", "song", None),
        ("Song [with Someone]", "song", None),
        ("Album (Deluxe Edition)", "album", "Deluxe Edition"),
        ("Album - Remastered 2011", "album", "Remastered 2011"),
        ("Track - Single", "track", None),
        ("Hey (Radio Mix) (Live)", "heyradiomix", "Live"),
        ("Without You", "withoutyou", None),
    ],
)
def test_split_title(title: str, key: str, edition: str | None) -> None:
    assert split_title(title) == (key, edition)


def link(
    key: str,
    title: str,
    day: str,
    *,
    kind: str = "album",
    tracks: int = 10,
    platform: str = "spotify",
    artist: str = "spotify:artist:A1",
) -> LinkState:
    item = SourceItem(
        key=key,
        platform=platform,
        id=key.rsplit(":", 1)[1],
        url=f"https://example.test/{key}",
        title=title,
        type=kind,
        artists=[ItemArtist(key=artist, name="Artiste")],
        date=day,
        precision="day",
        tracks=tracks,
    )
    return LinkState(item=item, first_seen=SEEN, last_seen=SEEN, backfill=False, via=[artist])


def test_jumeaux_d_une_meme_plateforme() -> None:
    links = {
        "spotify:album:a": link("spotify:album:a", "Nuit blanche", "2026-10-09"),
        "spotify:album:b": link("spotify:album:b", "Nuit blanche", "2026-10-09"),
    }
    assert cluster(links) == [["spotify:album:a", "spotify:album:b"]]


@pytest.mark.parametrize(
    "other",
    [
        link("spotify:album:b", "Nuit blanche (Deluxe)", "2026-10-09"),  # édition différente
        link("spotify:album:b", "Nuit blanche", "2026-10-09", tracks=12),  # titres différents
        link("spotify:album:b", "Nuit blanche", "2026-10-02"),  # date différente
        link(
            "spotify:album:b", "Nuit blanche", "2026-10-09", artist="spotify:artist:A9"
        ),  # homonyme
    ],
)
def test_sorties_distinctes_non_fusionnees(other: LinkState) -> None:
    links = {
        "spotify:album:a": link("spotify:album:a", "Nuit blanche", "2026-10-09"),
        "spotify:album:b": other,
    }
    assert len(cluster(links)) == 2


def test_regles_entre_plateformes() -> None:
    album_ = link("spotify:album:a", "Nuit blanche", "2026-10-09", tracks=10)
    single = link("spotify:album:s", "Nuit blanche", "2026-10-09", kind="single", tracks=1)
    track = link(
        "soundcloud:tracks:t",
        "Nuit blanche",
        "2026-10-04",
        kind="track",
        tracks=1,
        platform="soundcloud",
    )
    links = {"spotify:album:a": album_, "spotify:album:s": single, "soundcloud:tracks:t": track}
    # Le son SoundCloud rejoint le single (±7 jours) mais pas l'album (nombre de titres différent).
    assert sorted(cluster(links)) == [
        ["soundcloud:tracks:t", "spotify:album:s"],
        ["spotify:album:a"],
    ]


def test_identifiant_de_sortie_stable() -> None:
    assert release_id("spotify:album:a") == release_id("spotify:album:a")
    assert release_id("spotify:album:a").startswith("r_")
    assert release_id("spotify:album:a") != release_id("spotify:album:b")
