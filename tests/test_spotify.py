from dataclasses import replace
from datetime import date, timedelta

from newrel.models import FollowedArtist
from newrel.sources import spotify
from newrel.sources.spotify import album_to_item
from tests.helpers import CONFIG, NOW, collect_quickly, make_context, quick_http
from tests.spotify_fake import album


def followed(*ids: str) -> tuple[FollowedArtist, ...]:
    return tuple(FollowedArtist(key=f"spotify:artist:{i}", name=f"Artiste {i}") for i in ids)


def singles(prefix: str, *days: str, artist: str = "A1") -> list[dict]:
    return [
        album(f"{prefix}{n}", f"Titre {prefix}{n}", day, artists=((artist, "X"),))
        for n, day in enumerate(days)
    ]


def days_back(count: int, start: date = date(2026, 10, 20)) -> list[str]:
    return [(start - timedelta(days=n)).isoformat() for n in range(count)]


def group_calls(fake_spotify, group: str) -> int:
    calls = fake_spotify.albums_route.calls
    return sum(call.request.url.params["include_groups"] == group for call in calls)


# --- Normalisation ------------------------------------------------------------------------------


def test_un_single_de_quatre_titres_est_un_ep_deduit() -> None:
    item = album_to_item(album("E1", "Basse saison", "2026-10-16", tracks=5))
    assert item is not None
    assert (item.type, item.type_inferred, item.tracks) == ("ep", True, 5)
    assert item.key == "spotify:album:E1"
    assert item.cover == "https://i.scdn.co/image/E1-300"
    assert item.url == "https://open.spotify.com/album/E1"


def test_album_et_single_gardent_leur_type() -> None:
    long = album_to_item(album("L1", "Long", "2026-10-16", album_type="album", tracks=12))
    short = album_to_item(album("S1", "Court", "2026-10-16", tracks=2))
    assert (long.type, short.type) == ("album", "single")


def test_compilations_et_dates_invalides_ignorees() -> None:
    assert album_to_item(album("C1", "Best of", "2026-10-16", album_type="compilation")) is None
    assert album_to_item(album("Z1", "Vieux", "0000", precision="year")) is None


def test_precision_deduite_du_format_quand_elle_ne_correspond_pas() -> None:
    item = album_to_item(album("M1", "Mois", "2026-10", precision="day"))
    assert item is not None
    assert (item.date, item.precision) == ("2026-10", "month")


# --- Abonnements --------------------------------------------------------------------------------


def test_abonnements_pagines_par_curseur(fake_spotify) -> None:
    fake_spotify.follow(*[(f"A{n}", f"Artiste {n}") for n in range(120)])
    result = collect_quickly(make_context())
    assert result.status == "ok"
    assert len(result.followings) == 120
    assert fake_spotify.following_route.call_count == 3


def test_refresh_token_expire_fige_les_abonnements(fake_spotify) -> None:
    fake_spotify.refresh_error = "invalid_grant"
    fake_spotify.publish("A1", "single", *singles("s", "2026-10-16"))
    result = collect_quickly(make_context(previous_followings=followed("A1")))
    assert result.status == "auth_expired"
    assert "uv run newrel auth spotify" in result.message
    assert result.followings is None
    assert [item.key for item in result.checked["spotify:artist:A1"]] == ["spotify:album:s0"]


def test_chute_brutale_des_abonnements_ignoree(fake_spotify) -> None:
    previous = followed(*[f"A{n}" for n in range(10)])
    fake_spotify.follow(("A1", "Artiste 1"), ("A2", "Artiste 2"))
    result = collect_quickly(make_context(previous_followings=previous))
    assert result.status == "error"
    assert result.followings is None
    assert len(result.checked) == 10  # catalogue vérifié sur la liste précédente

    accepted = collect_quickly(make_context(previous_followings=previous, accept_drop=True))
    assert accepted.status == "ok"
    assert len(accepted.followings) == 2


def test_nouveau_refresh_token_signale(fake_spotify) -> None:
    fake_spotify.rotate = True
    result = collect_quickly(make_context())
    assert result.status == "ok"
    assert any("nouveau refresh token" in warning for warning in result.warnings)


# --- Catalogue ----------------------------------------------------------------------------------


def test_premier_passage_une_page_par_groupe(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"), ("A3", "Trois"))
    for artist in ("A1", "A2", "A3"):
        fake_spotify.publish(
            artist, "single", *singles(f"{artist}s", *days_back(15), artist=artist)
        )
        long = album(f"{artist}L", "Long", "2026-09-01", album_type="album", tracks=10)
        fake_spotify.publish(artist, "album", long)
    result = collect_quickly(make_context())
    assert fake_spotify.albums_route.call_count == 6  # 3 artistes × 2 groupes, une page chacun
    assert all(len(items) == 11 for items in result.checked.values())


def test_artiste_connu_pagine_jusqu_a_une_sortie_deja_vue(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days_back(25)))
    context = make_context(
        previous_followings=followed("A1"),
        baselined_artists=frozenset({"spotify:artist:A1"}),
        known_links=frozenset({"spotify:album:s12"}),
    )
    result = collect_quickly(context)
    assert group_calls(fake_spotify, "single") == 2  # la page 2 contient s12 : pas de page 3
    assert len(result.checked["spotify:artist:A1"]) == 20


def test_sorties_trop_anciennes_arretent_la_pagination(fake_spotify) -> None:
    days = ["2026-10-20"] * 9 + ["2026-06-01"] * 6  # la 10e sortie est hors fenêtre
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days))
    context = make_context(
        previous_followings=followed("A1"), baselined_artists=frozenset({"spotify:artist:A1"})
    )
    collect_quickly(context)
    assert group_calls(fake_spotify, "single") == 1


def test_ordre_inattendu_prolonge_la_pagination(fake_spotify) -> None:
    days = ["2026-08-01", *["2026-10-01"] * 9, *["2026-07-30"] * 3]
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days))
    context = make_context(
        previous_followings=followed("A1"),
        baselined_artists=frozenset({"spotify:artist:A1"}),
        known_links=frozenset({"spotify:album:s0"}),
    )
    result = collect_quickly(context)
    assert len(result.checked["spotify:artist:A1"]) == 13
    assert any("ordre inattendu" in warning for warning in result.warnings)


def test_limite_de_debit_rend_le_run_partiel(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"), ("A3", "Trois"))
    fake_spotify.rate_limited_artists = {"A2"}
    result = collect_quickly(make_context())
    assert result.status == "partial"
    assert "2 artiste(s) reporté(s)" in result.message
    assert list(result.checked) == ["spotify:artist:A1"]


def test_artiste_en_erreur_n_empeche_pas_les_autres(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"), ("A3", "Trois"))
    fake_spotify.failing_artists = {"A2"}
    result = collect_quickly(make_context())
    assert result.status == "partial"
    assert sorted(result.checked) == ["spotify:artist:A1", "spotify:artist:A3"]


def test_artistes_les_moins_recemment_verifies_d_abord(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"))
    fake_spotify.rate_limited_artists = {"A1"}
    result = collect_quickly(make_context(last_checked={"spotify:artist:A1": NOW}))
    assert list(result.checked) == ["spotify:artist:A2"]  # A2 jamais vérifié : il passe avant


def test_budget_d_appels_d_un_run_normal(fake_spotify) -> None:
    artists = [f"A{n}" for n in range(20)]
    fake_spotify.follow(*[(artist, f"Artiste {artist}") for artist in artists])
    for artist in artists:
        fake_spotify.publish(artist, "single", *singles(f"{artist}s", "2026-10-10", artist=artist))
    context = make_context(
        previous_followings=followed(*artists),
        baselined_artists=frozenset(f"spotify:artist:{artist}" for artist in artists),
        known_links=frozenset(f"spotify:album:{artist}s0" for artist in artists),
    )
    result = collect_quickly(context)
    assert result.calls <= 2 * len(artists) + 10


def test_budget_de_temps_reporte_les_artistes_restants(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"))
    ticks = iter([0.0, 0.0, 10_000.0])
    budget = replace(CONFIG, spotify=replace(CONFIG.spotify, time_budget_minutes=1))
    context = make_context(config=budget)
    result = spotify.collect(context, http=quick_http(), clock=lambda: next(ticks))
    assert result.status == "partial"
    assert list(result.checked) == ["spotify:artist:A1"]
