import json
from datetime import timedelta
from pathlib import Path

import pytest

from newrel import pipeline
from newrel.config import Aliases
from newrel.sources.base import SourceResult, SourceSpec
from tests.helpers import CONFIG, ENV, NOW, SC_ENV, SOURCES
from tests.soundcloud_fake import sc_playlist, sc_track, sc_user
from tests.spotify_fake import album

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
DAY = timedelta(days=1)


def run(tmp_path: Path, now=NOW, **options):
    options.setdefault("env", ENV)
    options.setdefault("sources", SOURCES)
    return pipeline.run(
        config=CONFIG,
        state_dir=tmp_path / "data",
        out_dir=tmp_path / "_site",
        site_dir=SITE_DIR,
        now=now,
        **options,
    )


def published(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "_site" / "releases.json").read_text(encoding="utf-8"))


def by_title(tmp_path: Path) -> dict[str, dict]:
    return {release["title"]: release for release in published(tmp_path)["releases"]}


@pytest.fixture
def one_artist(fake_spotify):
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.publish("A1", "single", album("s1", "Lumières froides", "2026-10-16"))
    fake_spotify.publish(
        "A1", "album", album("l1", "Échos", "2026-09-26", album_type="album", tracks=11)
    )
    return fake_spotify


def test_premier_run_catalogue_en_historique_sauf_sorties_recentes(tmp_path, one_artist) -> None:
    outcome = run(tmp_path)
    releases = by_title(tmp_path)
    assert set(releases) == {"Lumières froides", "Échos"}
    assert releases["Échos"]["backfill"] is True  # 26 jours : catalogue
    assert releases["Lumières froides"]["backfill"] is False  # 6 jours : badge « Nouveau »
    assert [item.title for item in outcome.reports[0].new_releases] == ["Lumières froides"]
    assert outcome.state_written
    assert (tmp_path / "data" / "state.json").exists()
    assert (tmp_path / "data" / "releases.json").read_text(encoding="utf-8") == (
        tmp_path / "_site" / "releases.json"
    ).read_text(encoding="utf-8")
    assert (tmp_path / "_site" / "index.html").exists()
    assert not (tmp_path / "_site" / "sample.json").exists()
    assert any("démarrage à zéro" in message for _, message in outcome.verdict.messages)
    assert published(tmp_path)["sources"]["spotify"] == {
        "status": "ok",
        "message": None,
        "last_success_at": "2026-10-22T04:17:00Z",
        "followed": 1,
        "unchecked": 0,
        "checked_last_run": 1,
        "oldest_check_at": "2026-10-22T04:17:00Z",
        "quota_reset_at": None,
    }


def test_quota_epuise_memorise_d_un_run_a_l_autre(tmp_path, one_artist) -> None:
    one_artist.follow(("A2", "Amel Rami"))
    one_artist.quota = 1  # le 2e appel catalogue du run est refusé
    run(tmp_path)
    assert published(tmp_path)["sources"]["spotify"]["unchecked"] == 2
    calls = one_artist.catalog_calls
    run(tmp_path, now=NOW + timedelta(hours=1))  # blocage en cours : aucun appel catalogue
    assert one_artist.catalog_calls == calls
    spotify_summary = published(tmp_path)["sources"]["spotify"]
    assert "quota épuisé jusqu'au 23/10" in spotify_summary["message"]
    assert spotify_summary["quota_reset_at"] == "2026-10-23T04:12:11Z"
    assert spotify_summary["checked_last_run"] == 0
    one_artist.quota = None
    run(tmp_path, now=NOW + DAY)  # Retry-After écoulé : la collecte reprend
    assert published(tmp_path)["sources"]["spotify"]["unchecked"] == 0
    assert published(tmp_path)["sources"]["spotify"]["status"] == "ok"


def test_nouvelle_sortie_detectee_le_lendemain(tmp_path, one_artist) -> None:
    run(tmp_path)
    before = by_title(tmp_path)
    one_artist.publish("A1", "single", album("s2", "Nouveau jour", "2026-10-23"))
    outcome = run(tmp_path, now=NOW + DAY)
    after = by_title(tmp_path)
    assert after["Nouveau jour"]["backfill"] is False
    assert after["Nouveau jour"]["first_seen"] == "2026-10-23T04:17:00Z"
    for title in ("Lumières froides", "Échos"):
        assert after[title]["id"] == before[title]["id"]
        assert after[title]["first_seen"] == before[title]["first_seen"]
    assert [item.title for item in outcome.reports[0].new_releases] == ["Nouveau jour"]
    assert published(tmp_path)["releases"][0]["title"] == "Nouveau jour"


def test_artiste_suivi_apres_coup_catalogue_en_historique(tmp_path, one_artist) -> None:
    run(tmp_path)
    one_artist.follow(("A2", "Amel Rami"))
    amel = (("A2", "Amel Rami"),)
    one_artist.publish(
        "A2",
        "single",
        album("t1", "Tout doux", "2026-10-21", artists=amel),
        album("t0", "Vieux tube", "2026-09-01", artists=amel),
        album("y0", "Archives", "2026", precision="year", artists=amel),
    )
    run(tmp_path, now=NOW + DAY)
    releases = by_title(tmp_path)
    assert releases["Tout doux"]["backfill"] is False  # sortie récente : nouveauté
    assert releases["Vieux tube"]["backfill"] is True
    # Datée à l'année et trouvée au premier passage : rangée au 1er janvier, donc hors fenêtre.
    assert "Archives" not in releases


def test_artiste_plus_suivi_retire_de_la_page(tmp_path, one_artist) -> None:
    one_artist.follow(("A2", "Amel Rami"))
    run(tmp_path)
    one_artist.unfollow("A1")
    run(tmp_path, now=NOW + DAY, accept_drop=True)  # 2 → 1 abonnement : chute volontaire
    assert by_title(tmp_path) == {}


def test_panne_conserve_les_donnees_et_rougit_au_deuxieme_echec(tmp_path, one_artist) -> None:
    run(tmp_path)
    one_artist.tokens_down = True
    first = run(tmp_path, now=NOW + DAY)
    assert set(by_title(tmp_path)) == {"Lumières froides", "Échos"}
    assert published(tmp_path)["sources"]["spotify"]["status"] == "error"
    assert first.verdict.level == "warning"
    second = run(tmp_path, now=NOW + 2 * DAY)
    assert second.verdict.level == "error"
    assert set(by_title(tmp_path)) == {"Lumières froides", "Échos"}


def test_refresh_token_expire_rougit_mais_le_catalogue_avance(tmp_path, one_artist) -> None:
    run(tmp_path)
    one_artist.refresh_error = "invalid_grant"
    one_artist.publish("A1", "single", album("s2", "Nouveau jour", "2026-10-23"))
    outcome = run(tmp_path, now=NOW + DAY)
    assert outcome.verdict.level == "error"
    assert by_title(tmp_path)["Nouveau jour"]["backfill"] is False
    assert published(tmp_path)["sources"]["spotify"]["status"] == "auth_expired"


def test_source_qui_plante_est_isolee(tmp_path) -> None:
    def crash(_context):
        raise RuntimeError("bug")

    sources = {"spotify": SourceSpec(required_env=("SPOTIFY_CLIENT_ID",), collect=crash)}
    outcome = run(tmp_path, sources=sources)
    assert outcome.state_written
    assert (
        published(tmp_path)["sources"]["spotify"]["message"] == "erreur inattendue (RuntimeError)"
    )
    assert outcome.verdict.level == "warning"


def test_fenetre_de_90_jours(tmp_path, fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish(
        "A1",
        "single",
        album("recent", "Récent", "2026-10-01"),
        album("limite", "Limite", "2026-07-30"),
        album("ancien", "Ancien", "2026-07-01"),
    )
    run(tmp_path)
    assert set(by_title(tmp_path)) == {"Récent", "Limite"}
    run(tmp_path, now=NOW + 14 * DAY)  # la fenêtre commence le 7 août
    assert set(by_title(tmp_path)) == {"Récent"}
    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))
    assert "spotify:album:limite" not in state["links"]


def test_sortie_datee_a_l_annee_classee_au_jour_de_detection(tmp_path, one_artist) -> None:
    run(tmp_path)
    one_artist.publish(
        "A1", "album", album("y1", "Archives", "2026", precision="year", album_type="album")
    )
    run(tmp_path, now=NOW + DAY)
    archives = by_title(tmp_path)["Archives"]
    assert (archives["precision"], archives["sort_date"], archives["backfill"]) == (
        "year",
        "2026-10-23",
        False,
    )


def test_deux_runs_identiques_donnent_le_meme_resultat(tmp_path, one_artist) -> None:
    run(tmp_path)
    first = (tmp_path / "data" / "releases.json").read_bytes()
    run(tmp_path)
    assert (tmp_path / "data" / "releases.json").read_bytes() == first


def test_hors_ligne_sans_appel_ni_ecriture_d_etat(tmp_path, one_artist) -> None:
    run(tmp_path)
    state_before = (tmp_path / "data" / "state.json").read_bytes()
    calls_before = one_artist.token_route.call_count + one_artist.albums_route.call_count
    outcome = run(tmp_path, now=NOW + DAY, offline=True)
    assert not outcome.state_written
    assert one_artist.token_route.call_count + one_artist.albums_route.call_count == calls_before
    assert (tmp_path / "data" / "state.json").read_bytes() == state_before
    assert published(tmp_path)["generated_at"] == "2026-10-22T04:17:00Z"


def test_sans_secrets_le_site_est_construit_sans_etat(tmp_path) -> None:
    outcome = run(tmp_path, env={})
    assert not outcome.state_written
    assert published(tmp_path)["releases"] == []
    assert any("non configuré" in message for _, message in outcome.verdict.messages)


def test_etat_illisible_arrete_tout(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.json").write_text("{pas du json", encoding="utf-8")
    with pytest.raises(pipeline.FatalError):
        run(tmp_path)
    assert not (tmp_path / "_site").exists()


def test_jumeaux_explicit_clean_fusionnes(tmp_path, fake_spotify) -> None:
    fake_spotify.follow(("A1", "Un"))
    fake_spotify.publish(
        "A1",
        "album",
        album("explicit", "Nuit blanche", "2026-10-09", album_type="album", tracks=10),
        album("clean", "Nuit blanche", "2026-10-09", album_type="album", tracks=10),
    )
    run(tmp_path)
    data = published(tmp_path)
    assert [release["title"] for release in data["releases"]] == ["Nuit blanche"]
    assert len(data["aliases"]) == 1
    assert list(data["aliases"].values()) == [data["releases"][0]["id"]]


@pytest.fixture
def same_release_twice(fake_spotify, fake_soundcloud):
    """« Lumières froides » de Nora Velasco, sur Spotify et sur SoundCloud (préfixe et suffixe)."""
    fake_spotify.follow(("A1", "Nora Velasco"))
    single = album("s1", "Lumières froides", "2026-10-16", artists=(("A1", "Nora Velasco"),))
    fake_spotify.publish("A1", "single", single)
    user = sc_user(10, "Nora Velasco Official", permalink="noravelasco")
    fake_soundcloud.follow(user)
    title = "Nora Velasco - Lumières froides [Free DL]"
    fake_soundcloud.upload(user, sc_track(5, title, "2026/10/15 10:00:00 +0000", user))
    return fake_spotify, fake_soundcloud


def test_meme_sortie_sur_deux_plateformes_une_seule_carte(tmp_path, same_release_twice) -> None:
    run(tmp_path, env=ENV | SC_ENV)
    releases = published(tmp_path)["releases"]
    assert [release["title"] for release in releases] == ["Lumières froides"]
    assert [link["platform"] for link in releases[0]["links"]] == ["spotify", "soundcloud"]
    assert len(releases[0]["artists"]) == 1  # Nora Velasco, une seule fois
    assert releases[0]["date"] == "2026-10-16"  # la date Spotify, plus sûre qu'un upload
    assert set(published(tmp_path)["sources"]) == {"spotify", "soundcloud"}


def test_homonymes_declares_jamais_fusionnes(tmp_path, same_release_twice) -> None:
    never = Aliases(never=(frozenset({"spotify:artist:A1", "soundcloud:users:10"}),))
    run(tmp_path, env=ENV | SC_ENV, aliases=never)
    titles = [release["title"] for release in published(tmp_path)["releases"]]
    assert sorted(titles) == ["Lumières froides", "Nora Velasco - Lumières froides [Free DL]"]


def test_album_soundcloud_couvre_ses_sons(tmp_path, fake_soundcloud) -> None:
    user = sc_user(10, "Nora Velasco", permalink="noravelasco")
    fake_soundcloud.follow(user)
    tracks = tuple(sc_track(n, f"Titre {n}", "2026/10/16 08:00:00 +0000", user) for n in (1, 2))
    fake_soundcloud.upload(user, *tracks)
    album_ = sc_playlist(7, "Échos", "2026/10/16 09:00:00 +0000", user, tracks=tracks)
    fake_soundcloud.publish(user, album_)
    run(tmp_path, env=SC_ENV)
    releases = published(tmp_path)["releases"]
    assert [(release["title"], release["type"]) for release in releases] == [("Échos", "album")]


def test_resultat_d_une_source_sans_artistes_verifies(tmp_path) -> None:
    def empty(_context):
        return SourceResult(platform="spotify", status="ok")

    sources = {"spotify": SourceSpec(required_env=(), collect=empty)}
    outcome = run(tmp_path, sources=sources, env={})
    assert outcome.state_written
    assert published(tmp_path)["sources"]["spotify"]["status"] == "ok"
