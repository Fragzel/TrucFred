from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from newrel.http import HttpError
from newrel.models import ArtistState, FollowedArtist
from newrel.sources.soundcloud import (
    TOKEN_URL,
    SoundCloudApi,
    playlist_to_item,
    release_type,
    track_to_item,
)
from tests.helpers import (
    CONFIG,
    ENV,
    NOW,
    SC_ENV,
    collect_soundcloud_quickly,
    make_context,
    quick_http,
)
from tests.soundcloud_fake import sc_playlist, sc_track, sc_user

PARIS = ZoneInfo("Europe/Paris")
DAY = timedelta(days=1)


def nora() -> dict:
    """Un compte neuf à chaque test : upload() et publish() modifient ses compteurs."""
    return sc_user(10, "Nora Velasco", permalink="noravelasco")


def context(**overrides):
    return make_context(env=ENV | SC_ENV, **overrides)


def known(user: dict, total: int, full_ago: timedelta = DAY) -> dict[str, ArtistState]:
    return {
        user["urn"]: ArtistState(
            name=user["username"],
            baseline_at=NOW - 30 * DAY,
            last_checked_at=NOW - DAY,
            catalog_total=total,
            last_full_at=NOW - full_ago,
        )
    }


# --- Normalisation ------------------------------------------------------------------------------


def test_date_soundcloud_convertie_en_jour_local() -> None:
    item = track_to_item(sc_track(1, "Nuit", "2026/10/21 22:30:00 +0000", nora()), PARIS)
    assert (item.date, item.precision, item.type) == ("2026-10-22", "day", "track")
    assert item.key == "soundcloud:tracks:1"
    assert item.artists[0].key == "soundcloud:users:10"


def test_pochette_300_px_et_sons_bloques_ignores() -> None:
    track = sc_track(2, "Nuit", "2026/10/21 10:00:00 +0000", nora())
    assert track_to_item(track, PARIS).cover == "https://i1.sndcdn.com/artworks-2-t300x300.jpg"
    assert track_to_item({**track, "access": "blocked"}, PARIS) is None
    assert track_to_item({**track, "created_at": "hier"}, PARIS) is None


@pytest.mark.parametrize(
    ("value", "tracks", "expected"),
    [
        ("album", 9, "album"),
        ("ALBUM", 9, "album"),
        ("ep", 4, "ep"),
        ("single", 1, "single"),
        ("ep single", 2, "single"),
        ("ep single", 5, "ep"),
        ("compilation", 12, None),
        ("playlist", 30, None),
        ("", 3, None),
        (None, 3, None),
    ],
)
def test_types_de_playlist(value, tracks, expected) -> None:
    assert release_type(value, tracks) == expected


def test_album_et_ses_sons() -> None:
    user = nora()
    tracks = tuple(sc_track(n, f"T{n}", "2026/10/16 08:00:00 +0000", user) for n in (3, 4))
    album = sc_playlist(7, "Échos", "2026/10/16 09:00:00 +0000", user, tracks=tracks)
    item, members = playlist_to_item(album, PARIS)
    assert (item.type, item.tracks, item.key) == ("album", 2, "soundcloud:playlists:7")
    assert members == ["soundcloud:tracks:3", "soundcloud:tracks:4"]
    mix = sc_playlist(8, "Mix", "2026/10/16 09:00:00 +0000", user, playlist_type="playlist")
    assert playlist_to_item(mix, PARIS) == (None, [])


def test_genre_declare_et_tags_de_sa_famille() -> None:
    tags = 'acid "hard techno" hiphop Paris'
    track = sc_track(1, "Nuit", "2026/10/16 08:00:00 +0000", nora(), genre="Techno", tags=tags)
    assert track_to_item(track, PARIS).genres == ["Techno", "acid", "hard techno"]
    untagged = sc_track(2, "Jour", "2026/10/16 08:00:00 +0000", nora(), tags="dnb rap")
    assert track_to_item(untagged, PARIS).genres == ["dnb", "rap"]  # sans genre : pas de tri
    album = sc_playlist(7, "Échos", "2026/10/16 09:00:00 +0000", nora(), genre="Drum & Bass")
    assert playlist_to_item(album, PARIS)[0].genres == ["Drum & Bass"]


def test_titres_d_une_playlist() -> None:
    user = nora()
    tracks = (
        sc_track(3, "Un", "2026/10/16 08:00:00 +0000", user),
        {**sc_track(4, "Bloqué", "2026/10/16 08:00:00 +0000", user), "access": "blocked"},
        sc_track(5, "Deux", "2026/10/16 08:00:00 +0000", user),
    )
    album = sc_playlist(7, "Échos", "2026/10/16 09:00:00 +0000", user, tracks=tracks)
    item, _ = playlist_to_item(album, PARIS)
    assert [(t.title, t.url) for t in item.tracklist] == [
        ("Un", "https://soundcloud.com/noravelasco/son-3"),
        ("Deux", "https://soundcloud.com/noravelasco/son-5"),
    ]


# --- Collecte -----------------------------------------------------------------------------------


def test_comptes_suivis_pagines_et_exclusions(fake_soundcloud) -> None:
    fake_soundcloud.follow(*[sc_user(100 + n, f"Compte {n}") for n in range(250)])
    fake_soundcloud.follow(sc_user(999, "Mon label", permalink="monlabel"))
    config = replace(CONFIG, soundcloud=replace(CONFIG.soundcloud, exclude=("monlabel",)))
    result = collect_soundcloud_quickly(context(config=config))
    assert result.status == "ok"
    assert len(result.followings) == 250
    assert fake_soundcloud.followings_route.call_count == 2  # 200 par page


def test_premier_passage_rattache_les_sons_a_leur_album(fake_soundcloud) -> None:
    user = nora()
    fake_soundcloud.follow(user)
    tracks = [sc_track(n, f"Titre {n}", "2026/10/16 08:00:00 +0000", user) for n in (1, 2, 3)]
    fake_soundcloud.upload(user, *tracks)
    album = sc_playlist(7, "Échos", "2026/10/16 09:00:00 +0000", user, tracks=tuple(tracks[:2]))
    fake_soundcloud.publish(user, album)
    check = collect_soundcloud_quickly(context()).checked[user["urn"]]
    assert {item.key: item.parent for item in check.items} == {
        "soundcloud:playlists:7": None,
        "soundcloud:tracks:1": "soundcloud:playlists:7",
        "soundcloud:tracks:2": "soundcloud:playlists:7",
        "soundcloud:tracks:3": None,
    }
    assert (check.catalog_total, check.full) == (4, True)


def test_compteurs_inchanges_aucun_appel(fake_soundcloud) -> None:
    user = nora()
    fake_soundcloud.follow(user)
    fake_soundcloud.upload(user, sc_track(1, "Nuit", "2026/10/10 08:00:00 +0000", user))
    check = collect_soundcloud_quickly(context(artists=known(user, total=1))).checked[user["urn"]]
    assert fake_soundcloud.catalog_calls == 0
    assert (check.full, check.catalog_total) == (False, 1)


def test_compteurs_en_hausse_ou_relecture_mensuelle(fake_soundcloud) -> None:
    user = nora()
    fake_soundcloud.follow(user)
    fake_soundcloud.upload(user, sc_track(1, "Nuit", "2026/10/10 08:00:00 +0000", user))
    fake_soundcloud.upload(user, sc_track(2, "Jour", "2026/10/21 08:00:00 +0000", user))
    result = collect_soundcloud_quickly(context(artists=known(user, total=1)))
    assert fake_soundcloud.catalog_calls == 2  # sons + playlists
    assert "soundcloud:tracks:2" in [item.key for item in result.checked[user["urn"]].items]
    collect_soundcloud_quickly(context(artists=known(user, total=2, full_ago=31 * DAY)))
    assert fake_soundcloud.catalog_calls == 4  # compteurs stables, mais relecture du mois


def test_compte_lu_avant_les_genres_relu_une_fois(fake_soundcloud) -> None:
    user = nora()
    fake_soundcloud.follow(user)
    fake_soundcloud.upload(
        user, sc_track(1, "Nuit", "2026/10/10 08:00:00 +0000", user, genre="Gabber")
    )
    stale = frozenset({user["urn"]})
    result = collect_soundcloud_quickly(context(artists=known(user, total=1), stale_artists=stale))
    assert fake_soundcloud.catalog_calls == 2  # compteurs stables, mais genres à collecter
    assert result.checked[user["urn"]].items[0].genres == ["Gabber"]


def test_comptes_suivis_refuses_en_client_credentials(fake_soundcloud) -> None:
    fake_soundcloud.followings_status = 401
    previous = (FollowedArtist(key="soundcloud:users:10", name="Nora Velasco"),)
    result = collect_soundcloud_quickly(context(previous_followings=previous))
    assert result.status == "error"
    assert "Client Credentials" in result.message
    assert result.followings is None
    assert list(result.checked) == ["soundcloud:users:10"]  # la liste précédente reste vérifiée


def test_jeton_jamais_envoye_hors_de_l_api(router) -> None:
    router.post(TOKEN_URL).respond(200, json={"access_token": "sc-token"})
    router.route(host="api.soundcloud.com", path="/users/1/followings").respond(
        200, json={"collection": [], "next_href": "https://evil.example/next"}
    )
    evil = router.route(host="evil.example").respond(200, json={"collection": []})
    api = SoundCloudApi(quick_http(), "sc-client-id", "sc-client-secret")
    with pytest.raises(HttpError, match="hors de l'API"):
        api.collection("/users/1/followings", {}, max_pages=3)
    assert not evil.called


def test_titres_des_playlists_connues_lus_une_fois(fake_soundcloud) -> None:
    user = nora()
    fake_soundcloud.follow(user)
    track = sc_track(3, "Un", "2026/10/10 08:00:00 +0000", user)
    fake_soundcloud.upload(user, track)
    album = sc_playlist(7, "Échos", "2026/10/10 09:00:00 +0000", user, tracks=(track,))
    fake_soundcloud.publish(user, album)
    wanted = ("soundcloud:playlists:7", "soundcloud:playlists:404")
    ctx = context(artists=known(user, total=2), tracklists_wanted=wanted)
    result = collect_soundcloud_quickly(ctx)
    assert fake_soundcloud.catalog_calls == 0  # compte inchangé : pas relu
    assert [t.title for t in result.tracklists["soundcloud:playlists:7"]] == ["Un"]
    assert result.tracklists["soundcloud:playlists:404"] == []
