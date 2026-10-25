from datetime import UTC, datetime

import pytest

from newrel.config import Aliases
from newrel.dedup import (
    artist_id,
    artist_name_key,
    canonical_artists,
    clean_title,
    cluster,
    release_id,
    split_title,
)
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
    tracks: int | None = 10,
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


@pytest.mark.parametrize(
    ("title", "names", "key"),
    [
        ("Nora Velasco - Lumières froides", ["Nora Velasco"], "lumieresfroides"),
        ("NORA VELASCO – Lumières froides [Free DL]", ["Nora Velasco Official"], "lumieresfroides"),
        ("Lumières froides (Clip officiel)", [], "lumieresfroides"),
        ("Autre Artiste - Lumières froides", ["Nora Velasco"], "autreartistelumieresfroides"),
    ],
)
def test_titres_soundcloud(title: str, names: list[str], key: str) -> None:
    assert split_title(title, names)[0] == key


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Nora Velasco", "noravelasco"),
        ("Nora Velasco Official", "noravelasco"),
        ("noravelascomusic", "noravelasco"),
        ("The Marées Hautes", "mareeshautes"),
        ("Bigflo et Oli", "bigflooli"),
        ("Bigflo & Oli", "bigflooli"),
    ],
)
def test_cle_de_nom_d_artiste(name: str, key: str) -> None:
    assert artist_name_key(name) == key


def test_artistes_reunis_entre_plateformes_sauf_homonymes_ou_refus() -> None:
    names = {
        "spotify:artist:A1": "Nora Velasco",
        "soundcloud:users:10": "Nora Velasco Official",
        "spotify:artist:K1": "Kid",
        "spotify:artist:K2": "Kid",  # deux « Kid » sur Spotify : ambigu
        "soundcloud:users:20": "kid",
    }
    canonical = canonical_artists(names)
    assert (
        canonical["soundcloud:users:10"]
        == canonical["spotify:artist:A1"]
        == artist_id("spotify:artist:A1")
    )
    assert (
        len(
            {
                canonical[key]
                for key in ("spotify:artist:K1", "spotify:artist:K2", "soundcloud:users:20")
            }
        )
        == 3
    )
    never = Aliases(never=(frozenset({"spotify:artist:A1", "soundcloud:users:10"}),))
    assert canonical_artists(names, never)["soundcloud:users:10"] != artist_id("spotify:artist:A1")
    same = Aliases(same=(frozenset({"spotify:artist:K1", "soundcloud:users:20"}),))
    forced = canonical_artists(names, same)
    assert (
        forced["soundcloud:users:20"] == forced["spotify:artist:K1"] != forced["spotify:artist:K2"]
    )


def test_identifiant_de_sortie_stable() -> None:
    assert release_id("spotify:album:a") == release_id("spotify:album:a")
    assert release_id("spotify:album:a").startswith("r_")
    assert release_id("spotify:album:a") != release_id("spotify:album:b")


@pytest.mark.parametrize(
    ("title", "names", "key", "shown"),
    [
        ("Nora Velasco - Nuit (Official Music Video)", ["Nora Velasco"], "nuit", "Nuit"),
        ("Nuit | Clip officiel | 4K", [], "nuit", "Nuit"),
        ("Nora Velasco ft. Kid - Nuit [Vidéo officielle]", ["NoraVelascoVEVO"], "nuit", "Nuit"),
        ("Nuit (feat. Kid) (Official Audio)", [], "nuit", "Nuit (feat. Kid)"),
        ("Nuit (Lyrics)", [], "nuit", "Nuit"),
        ("Nuit - Official 4K Video", [], "nuit", "Nuit"),
        ("Nuit (Remix) [Audio]", [], "nuit", "Nuit (Remix)"),
        ("Kid - Nuit", ["Nora Velasco"], "kidnuit", "Kid - Nuit"),
    ],
)
def test_titres_youtube(title: str, names: list[str], key: str, shown: str) -> None:
    assert split_title(title, names)[0] == key
    assert clean_title(title, names) == shown


def test_chaine_vevo_et_chaine_principale_un_seul_artiste() -> None:
    names = {
        "youtube:channel:UC1": "Nora Velasco",
        "youtube:channel:UC2": "NoraVelascoVEVO",
        "spotify:artist:A1": "Nora Velasco",
    }
    canonical = canonical_artists(names)
    assert len(set(canonical.values())) == 1
    assert canonical["youtube:channel:UC2"] == artist_id("spotify:artist:A1")


def test_clip_rejoint_le_single_et_les_autres_videos_du_titre() -> None:
    def video(key: str, title: str, day: str) -> LinkState:
        return link(key, title, day, kind="video", tracks=None, platform="youtube")

    links = {
        "spotify:album:s": link("spotify:album:s", "Nuit", "2026-10-16", kind="single", tracks=1),
        "spotify:album:a": link("spotify:album:a", "Nuit", "2026-10-16", tracks=10),
        "youtube:video:c": video("youtube:video:c", "Nuit (Clip officiel)", "2026-10-15"),
        "youtube:video:l": video("youtube:video:l", "Nuit (Lyric Video)", "2026-10-19"),
        "youtube:video:x": video("youtube:video:x", "Nuit (Live)", "2026-10-19"),
    }
    # Le clip et la lyric video rejoignent le single, pas l'album ; la version live reste à part.
    assert sorted(cluster(links)) == [
        ["spotify:album:a"],
        ["spotify:album:s", "youtube:video:c", "youtube:video:l"],
        ["youtube:video:x"],
    ]
