from dataclasses import replace
from datetime import date, timedelta

from newrel.models import ArtistState, FollowedArtist
from newrel.sources import spotify
from newrel.sources.spotify import album_to_item
from tests.helpers import CONFIG, NOW, collect_quickly, make_context, quick_http
from tests.spotify_fake import album

DAY = timedelta(days=1)


def followed(*ids: str) -> tuple[FollowedArtist, ...]:
    return tuple(FollowedArtist(key=f"spotify:artist:{i}", name=f"Artiste {i}") for i in ids)


def known(
    *ids: str,
    total: int | None = None,
    latest: date | None = None,
    checked_ago: timedelta = DAY,
    full_ago: timedelta = DAY,
) -> dict[str, ArtistState]:
    """Artistes déjà vérifiés ; sans total connu, le prochain passage est détaillé."""
    return {
        f"spotify:artist:{i}": ArtistState(
            name=f"Artiste {i}",
            baseline_at=NOW - 30 * DAY,
            last_checked_at=NOW - checked_ago,
            catalog_total=total,
            latest_release=latest,
            last_full_at=NOW - full_ago,
        )
        for i in ids
    }


def with_budget(calls: int):
    return replace(CONFIG, spotify=replace(CONFIG.spotify, daily_catalog_calls=calls))


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


def test_genres_des_artistes_suivis_sans_appel_catalogue(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.genres["A1"] = ["rap francais", "indie", "pop urbaine"]
    result = collect_quickly(make_context())
    assert result.followings[0].genres == ["rap francais", "pop urbaine"]  # « indie » : rien
    assert fake_spotify.catalog_calls == 2  # comme sans genres : albums et singles


def test_refresh_token_expire_fige_les_abonnements(fake_spotify) -> None:
    fake_spotify.refresh_error = "invalid_grant"
    fake_spotify.publish("A1", "single", *singles("s", "2026-10-16"))
    result = collect_quickly(make_context(previous_followings=followed("A1")))
    assert result.status == "auth_expired"
    assert "uv run newrel auth spotify" in result.message
    assert result.followings is None
    assert [item.key for item in result.checked["spotify:artist:A1"].items] == ["spotify:album:s0"]


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
    checks = list(result.checked.values())
    assert all(len(check.items) == 11 for check in checks)
    assert all((check.catalog_total, check.full) == (16, True) for check in checks)
    assert checks[0].latest_release == date(2026, 10, 20)


def test_artiste_connu_pagine_jusqu_a_une_sortie_deja_vue(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days_back(25)))
    context = make_context(
        previous_followings=followed("A1"),
        artists=known("A1"),
        known_links=frozenset({"spotify:album:s12"}),
    )
    result = collect_quickly(context)
    assert group_calls(fake_spotify, "single") == 2  # la page 2 contient s12 : pas de page 3
    assert len(result.checked["spotify:artist:A1"].items) == 20


def test_sorties_trop_anciennes_arretent_la_pagination(fake_spotify) -> None:
    days = ["2026-10-20"] * 9 + ["2026-06-01"] * 6  # la 10e sortie est hors fenêtre
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days))
    context = make_context(previous_followings=followed("A1"), artists=known("A1"))
    collect_quickly(context)
    assert group_calls(fake_spotify, "single") == 1


def test_ordre_inattendu_prolonge_la_pagination(fake_spotify) -> None:
    days = ["2026-08-01", *["2026-10-01"] * 9, *["2026-07-30"] * 3]
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", *days))
    context = make_context(
        previous_followings=followed("A1"),
        artists=known("A1"),
        known_links=frozenset({"spotify:album:s0"}),
    )
    result = collect_quickly(context)
    assert len(result.checked["spotify:artist:A1"].items) == 13
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


def test_artistes_jamais_verifies_d_abord(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"))
    fake_spotify.rate_limited_artists = {"A1"}
    result = collect_quickly(make_context(artists=known("A1", checked_ago=timedelta(0))))
    assert list(result.checked) == ["spotify:artist:A2"]  # A2 jamais vérifié : il passe avant


def test_artiste_actif_passe_avant_artiste_en_sommeil(fake_spotify) -> None:
    fake_spotify.follow(("A1", "En sommeil"), ("A2", "Actif"))
    artists = known("A1", total=0, latest=date(2024, 5, 1), checked_ago=3 * DAY) | known(
        "A2", total=0, latest=date(2026, 9, 1), checked_ago=1.5 * DAY
    )
    # 3 jours sur un rythme de 7 jours (0,43) contre 1,5 jour sur un rythme de 2 jours (0,75).
    result = collect_quickly(make_context(config=with_budget(3), artists=artists))
    assert list(result.checked) == ["spotify:artist:A2"]


def test_total_inchange_un_seul_appel_par_artiste(fake_spotify) -> None:
    artists = [f"A{n}" for n in range(20)]
    fake_spotify.follow(*[(artist, f"Artiste {artist}") for artist in artists])
    for artist in artists:
        fake_spotify.publish(artist, "single", *singles(f"{artist}s", "2026-10-10", artist=artist))
    context = make_context(previous_followings=followed(*artists), artists=known(*artists, total=1))
    result = collect_quickly(context)
    assert fake_spotify.catalog_calls == 20
    assert all(
        (c.items, c.catalog_total, c.full) == ([], 1, False) for c in result.checked.values()
    )
    assert result.checked["spotify:artist:A0"].latest_release == date(2026, 10, 10)


def test_total_en_hausse_declenche_la_lecture_detaillee(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", "2026-10-21", "2026-10-10"))
    context = make_context(
        previous_followings=followed("A1"),
        artists=known("A1", total=1),
        known_links=frozenset({"spotify:album:s1"}),
    )
    check = collect_quickly(context).checked["spotify:artist:A1"]
    assert fake_spotify.catalog_calls == 3  # total, puis singles et albums
    assert (check.catalog_total, check.full) == (2, True)
    assert "spotify:album:s0" in [item.key for item in check.items]


def test_relecture_complete_au_moins_une_fois_par_mois(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish("A1", "single", *singles("s", "2026-10-10"))
    artists = known("A1", total=1, full_ago=31 * DAY)
    check = collect_quickly(make_context(artists=artists)).checked["spotify:artist:A1"]
    assert (fake_spotify.catalog_calls, check.full) == (2, True)


def test_budget_quotidien_garde_la_suite_pour_le_prochain_run(fake_spotify) -> None:
    fake_spotify.follow(*[(f"A{n}", f"Artiste {n}") for n in range(10)])
    result = collect_quickly(make_context(config=with_budget(5)))
    assert result.status == "ok"  # budget atteint : fonctionnement normal, pas une alerte
    assert (len(result.checked), result.pending, fake_spotify.catalog_calls) == (2, 8, 4)


def test_quota_epuise_memorise_l_heure_de_reprise(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"), ("A3", "Trois"))
    fake_spotify.quota = 3
    result = collect_quickly(make_context())
    assert result.status == "partial"
    assert list(result.checked) == ["spotify:artist:A1"]
    assert result.pending == 2
    assert result.quota_reset_at == NOW + timedelta(seconds=86111)
    assert "reprise après le 23/10 à 06:12" in result.message


def test_quota_en_cours_aucun_appel_catalogue(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    reset = NOW + timedelta(hours=1)
    result = collect_quickly(make_context(quota_reset_at=reset))
    assert fake_spotify.catalog_calls == 0
    assert (result.status, result.pending, result.quota_reset_at) == ("partial", 1, reset)
    assert result.followings is not None  # les abonnements, eux, sont lus


def test_budget_de_temps_reporte_les_artistes_restants(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"), ("A2", "Deux"))
    ticks = iter([0.0, 0.0, 10_000.0])
    budget = replace(CONFIG, spotify=replace(CONFIG.spotify, time_budget_minutes=1))
    context = make_context(config=budget)
    result = spotify.collect(context, http=quick_http(), clock=lambda: next(ticks))
    assert result.status == "partial"
    assert list(result.checked) == ["spotify:artist:A1"]


def test_titres_des_ep_lus_sur_un_petit_budget_avant_les_artistes(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Artiste 1"))
    ep = album("e1", "Nuit", "2026-10-16", album_type="single", tracks=4)
    fake_spotify.publish("A1", "single", ep, album("e2", "Jour", "2026-10-09", tracks=5))
    config = replace(CONFIG, spotify=replace(CONFIG.spotify, tracklist_calls=1))
    wanted = ("spotify:album:e1", "spotify:album:e2", "spotify:album:disparu")
    result = collect_quickly(make_context(config=config, tracklists_wanted=wanted))
    assert list(result.tracklists) == ["spotify:album:e1"]  # budget de 1 : le plus récent
    tracks = result.tracklists["spotify:album:e1"]
    assert [(t.title, t.url, t.duration_ms) for t in tracks][:2] == [
        ("Nuit 1", "https://open.spotify.com/track/e1t1", 181_000),
        ("Nuit 2", "https://open.spotify.com/track/e1t2", 182_000),
    ]
    assert len(tracks) == 4 and fake_spotify.album_route.call_count == 1
    assert result.checked  # les artistes sont vérifiés ensuite, sur le reste du budget


def test_album_retire_du_catalogue_titres_vides(fake_spotify) -> None:
    fake_spotify.follow(("A1", "Artiste 1"))
    result = collect_quickly(make_context(tracklists_wanted=("spotify:album:disparu",)))
    assert result.tracklists == {"spotify:album:disparu": []}  # plus jamais redemandé
