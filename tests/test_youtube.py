from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from newrel.config import ConfigError, load_config
from newrel.models import ArtistState, FollowedArtist
from newrel.sources import youtube_triage
from newrel.sources.youtube import (
    Channel,
    duration_seconds,
    first_look,
    is_release,
    other_artists,
    second_look,
    video_to_item,
)
from newrel.sources.youtube_triage import TriageFile
from tests.helpers import CONFIG, NOW, YT_ENV, collect_youtube_quickly, make_context, quick_http
from tests.youtube_fake import yt_channel, yt_video

PARIS = ZoneInfo("Europe/Paris")
SETTINGS = CONFIG.youtube
DAY = timedelta(days=1)


def context(**overrides):
    return make_context(env=YT_ENV, **overrides)


def with_triage(artists=(), ignore=()):
    return replace(CONFIG, youtube=replace(SETTINGS, artists=artists, ignore=ignore))


def channel(title: str, topics: tuple[str, ...] = ("Music",)) -> Channel:
    return Channel(id="UC" + "0" * 22, title=title, handle="@x", topics=topics)


def nora() -> dict:
    return yt_channel(1, "Nora Velasco", topics=("Music", "Pop_music"), handle="@noravelasco")


def clips(prefix: str, count: int, artist: str = "Nora Velasco", **options) -> list[dict]:
    return [
        yt_video(
            f"{prefix}{n}",
            f"{artist} - Titre {prefix}{n} (Clip officiel)",
            f"2026-10-{20 - n:02d}T10:00:00Z",
            **options,
        )
        for n in range(count)
    ]


# --- Vidéos -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("PT3M45S", 225), ("PT1H2M", 3720), ("PT45S", 45), ("P0D", 0), ("P1DT1S", 86401), ("", None)],
)
def test_duree_iso_8601(value: str, seconds: int | None) -> None:
    assert duration_seconds(value) == seconds


@pytest.mark.parametrize(
    ("title", "options", "kept"),
    [
        ("Nora Velasco - Nuit (Clip officiel)", {}, True),
        ("Live Forever", {}, True),  # « live » au sens du titre, pas un concert
        ("Nuit", {"duration": "PT45S"}, False),  # Short ou extrait
        ("Nuit (teaser)", {}, False),
        ("Nuit - Behind The Scenes", {}, False),
        ("Nuit (Live)", {}, False),
        ("Nuit - Live at Bercy", {}, False),
        ("Nuit | Live Session", {}, False),
        ("Nuit #shorts", {"duration": "PT1M10S"}, False),
        ("Nuit", {"live": "upcoming"}, False),  # première pas encore diffusée
        ("Concert complet", {"duration": "PT1H30M"}, False),
        ("Ma journée en studio", {"category": "22"}, False),  # vlog hors catégorie Musique
        ("Nuit (Clip officiel)", {"category": "22"}, True),  # mention explicite
        ("Nora Velasco - Nuit", {"category": "22"}, True),  # « Artiste - Morceau » à son nom
        ("Kid Marin - Nuit", {"category": "22"}, False),
        ("Unbeleevable Ep.04 - The Egg", {}, False),  # épisode de web-série
    ],
)
def test_clips_et_audios_seulement(title: str, options: dict, kept: bool) -> None:
    video = yt_video("v", title, "2026-10-20T10:00:00Z", **options)
    assert is_release(video, SETTINGS, channel("Nora Velasco")) is kept


def test_video_en_sortie_titre_nettoye_et_jour_local() -> None:
    video = yt_video("abc", "Nora Velasco - Nuit (Official Music Video)", "2026-10-21T22:30:00Z")
    item = video_to_item(video, channel("Nora Velasco"), PARIS, SETTINGS)
    assert (item.key, item.type, item.title) == ("youtube:video:abc", "video", "Nuit")
    assert (item.date, item.precision) == ("2026-10-22", "day")
    assert item.url == "https://www.youtube.com/watch?v=abc"
    assert item.cover == "https://i.ytimg.com/vi/abc/mqdefault.jpg"
    assert item.artists[0].key == "youtube:channel:UC" + "0" * 22


# --- Tri ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "topics", "peers", "follow"),
    [
        ("Nora Velasco - Topic", (), set(), True),
        ("NoraVelascoVEVO", ("Music",), set(), True),
        ("Jeux et Astuces", ("Video_game_culture", "Action_game"), set(), False),
        ("Nora Velasco", ("Music",), {"noravelasco"}, True),
        ("Nora Velasco", (), {"noravelasco"}, True),
        ("Nora Velasco", ("Food",), {"noravelasco"}, None),  # homonyme ? on regarde les vidéos
        ("Nora Velasco", ("Music",), set(), None),
    ],
)
def test_premier_regard_sans_appel(title, topics, peers, follow) -> None:
    verdict = first_look(channel(title, topics), frozenset(peers))
    assert (verdict.follow if verdict else None) is follow
    assert (verdict is None) is (follow is None)


def test_second_regard_sur_les_dernieres_videos() -> None:
    artist = channel("Nora Velasco")
    assert second_look(artist, clips("a", 10), SETTINGS).follow is True
    label = [
        yt_video(f"l{n}", f"Artiste {n} - Titre (Official Video)", "2026-10-20T10:00:00Z")
        for n in range(6)
    ]
    verdict = second_look(channel("Label Records"), label, SETTINGS)
    assert verdict.follow is True and "label" in verdict.reason  # ses sorties comptent aussi
    vlog = clips("v", 10, category="22")
    assert second_look(channel("Vlog", ()), vlog, SETTINGS).follow is False
    assert second_look(channel("Vlog", ("Music",)), vlog, SETTINGS).follow is None
    # Artiste qui laisse ses vidéos dans la catégorie par défaut : ses titres le trahissent.
    verdict = second_look(channel("Nora Velasco", ("Music",)), vlog, SETTINGS)
    assert verdict.follow is True and "à son nom" in verdict.reason
    lives = clips("s", 10, duration="PT45M")
    assert second_look(artist, lives, SETTINGS).follow is True  # surtout des lives, mais à son nom
    assert second_look(channel("Sessions Live"), lives, SETTINGS).follow is None
    assert second_look(artist, [], SETTINGS).follow is None


def test_reprises_pas_comptees_comme_autres_artistes() -> None:
    covers = [
        yt_video(f"c{n}", f"Chanson {n} - Artiste Original {n} (cover)", "2026-10-20T10:00:00Z")
        for n in range(5)
    ]
    assert other_artists(channel("Nora Velasco"), covers) == set()


# --- Collecte -----------------------------------------------------------------------------------


@pytest.fixture
def subscriptions(fake_youtube):
    """Une artiste, une chaîne VEVO, un label, une chaîne de jeux vidéo et une chaîne de
    sessions hors catégorie Musique (douteuse)."""
    artist = nora()
    vevo = yt_channel(2, "KidMarinVEVO", topics=("Music",))
    label = yt_channel(3, "Label Records", topics=("Music", "Electronic_music"))
    games = yt_channel(4, "Jeux et Astuces", topics=("Video_game_culture",))
    sessions = yt_channel(5, "Studio Sessions", topics=("Music",))
    fake_youtube.subscribe(artist, vevo, label, games, sessions)
    fake_youtube.upload(artist, *clips("n", 8))
    fake_youtube.upload(
        artist,
        yt_video("short", "Nuit", "2026-10-21T09:00:00Z", duration="PT30S"),
        yt_video("tease", "Nora Velasco - Bientôt (Teaser)", "2026-10-21T08:00:00Z"),
    )
    fake_youtube.upload(
        vevo, yt_video("k1", "Kid Marin - Été (Official Video)", "2026-10-19T15:00:00Z")
    )
    fake_youtube.upload(
        label,
        *[yt_video(f"l{n}", f"Artiste {n} - Titre", "2026-10-10T10:00:00Z") for n in range(5)],
    )
    fake_youtube.upload(
        sessions,
        *[
            yt_video(f"s{n}", f"Invité {n} en studio", "2026-10-12T10:00:00Z", category="22")
            for n in range(5)
        ],
    )
    return fake_youtube


def test_tri_puis_clips_des_artistes_et_labels(subscriptions) -> None:
    result = collect_youtube_quickly(context())
    assert result.status == "ok"
    followed = [artist.name for artist in result.followings]
    assert followed == ["KidMarinVEVO", "Label Records", "Nora Velasco"]
    keys = {item.key for check in result.checked.values() for item in check.items}
    assert {"youtube:video:k1", "youtube:video:n0", "youtube:video:l0"} <= keys
    assert not {"youtube:video:short", "youtube:video:tease"} & keys
    assert result.warnings == [
        "YouTube : 1 chaîne(s) à trier, lance « uv run newrel triage youtube »"
    ]
    # Logs publics : les chaînes écartées ou douteuses ne sont jamais nommées.
    text = " ".join([*result.warnings, result.message or ""])
    assert "Studio" not in text and "Jeux" not in text


def test_decisions_de_youtube_toml(subscriptions) -> None:
    config = with_triage(artists=("UC" + "3".zfill(22),), ignore=("@noravelasco",))
    previous = (FollowedArtist(key="youtube:channel:UC" + "1".zfill(22), name="Nora Velasco"),)
    result = collect_youtube_quickly(context(config=config, previous_followings=previous))
    # Écarter à la main une chaîne suivie n'est pas une « chute brutale » des abonnements.
    assert result.status == "ok"
    assert [artist.name for artist in result.followings] == ["KidMarinVEVO", "Label Records"]
    assert len(result.warnings) == 1  # la chaîne de sessions, toujours à trier


def test_chaine_deja_suivie_reste_suivie(fake_youtube) -> None:
    label = yt_channel(3, "Label Records", topics=("Music",))
    fake_youtube.subscribe(label)
    fake_youtube.upload(
        label,
        *[yt_video(f"l{n}", f"Artiste {n} - Titre", "2026-10-10T10:00:00Z") for n in range(5)],
    )
    previous = (FollowedArtist(key="youtube:channel:" + label["id"], name="Label Records"),)
    result = collect_youtube_quickly(context(previous_followings=previous))
    assert [artist.name for artist in result.followings] == ["Label Records"]
    assert fake_youtube.playlist_route.call_count == 1  # lecture du catalogue, pas d'échantillon


def test_meme_nom_qu_un_artiste_spotify(fake_youtube) -> None:
    fake_youtube.subscribe(yt_channel(5, "Nora Velasco Officiel", topics=()))
    result = collect_youtube_quickly(context(peer_names=frozenset({"Nora Velasco"})))
    assert [artist.name for artist in result.followings] == ["Nora Velasco Officiel"]


def test_playlist_des_videos_longues_absente(fake_youtube) -> None:
    artist = nora()
    fake_youtube.subscribe(artist)
    fake_youtube.upload(artist, *clips("n", 3))
    fake_youtube.shorts_playlist_missing = True
    previous = (FollowedArtist(key="youtube:channel:" + artist["id"], name="Nora Velasco"),)
    result = collect_youtube_quickly(context(previous_followings=previous))
    items = result.checked["youtube:channel:" + artist["id"]].items
    assert len(items) == 3  # repli sur la playlist de toutes les vidéos


def test_artiste_connu_seules_les_videos_de_la_fenetre_sont_detaillees(fake_youtube) -> None:
    artist = nora()
    fake_youtube.subscribe(artist)
    fake_youtube.upload(artist, yt_video("old", "Ancien", "2026-01-10T10:00:00Z"))
    fake_youtube.upload(artist, *clips("n", 2))
    key = "youtube:channel:" + artist["id"]
    known = {
        key: ArtistState(name="Nora Velasco", baseline_at=NOW - 30 * DAY, last_checked_at=NOW - DAY)
    }
    previous = (FollowedArtist(key=key, name="Nora Velasco"),)
    result = collect_youtube_quickly(context(previous_followings=previous, artists=known))
    assert fake_youtube.videos_route.calls.last.request.url.params["id"] == "n0,n1"
    assert result.checked[key].latest_release.isoformat() == "2026-10-20"


def test_abonnements_redevenus_prives(fake_youtube) -> None:
    artist = nora()
    fake_youtube.subscribe(artist)
    fake_youtube.upload(artist, *clips("n", 2))
    fake_youtube.subscriptions_private = True
    previous = (FollowedArtist(key="youtube:channel:" + artist["id"], name="Nora Velasco"),)
    result = collect_youtube_quickly(context(previous_followings=previous))
    assert result.status == "error" and result.followings is None
    assert "Garder tous mes abonnements privés" in result.message
    # Les vidéos sont publiques : les chaînes déjà suivies continuent d'être vérifiées.
    assert len(result.checked["youtube:channel:" + artist["id"]].items) == 2


def test_quota_epuise_memorise_jusqu_a_minuit_heure_du_pacifique(subscriptions) -> None:
    subscriptions.quota_exceeded = True
    previous = (FollowedArtist(key="youtube:channel:UC" + "1".zfill(22), name="Nora Velasco"),)
    result = collect_youtube_quickly(context(previous_followings=previous))
    assert result.status == "partial" and result.followings is None
    assert subscriptions.calls == 1  # pas d'insistance une fois le quota épuisé
    # 04:17 UTC = 21:17 la veille à Los Angeles : reprise à minuit, soit 07:00 UTC.
    assert result.quota_reset_at == datetime(2026, 10, 22, 7, 0, tzinfo=UTC)
    calls = subscriptions.calls
    later = collect_youtube_quickly(context(quota_reset_at=result.quota_reset_at))
    assert later.status == "partial" and subscriptions.calls == calls
    assert later.quota_reset_at == result.quota_reset_at


def test_abonnements_indisponibles_liste_precedente_verifiee(fake_youtube) -> None:
    artist = nora()
    fake_youtube.subscribe(artist)
    fake_youtube.upload(artist, *clips("n", 2))
    fake_youtube.subscriptions_status = 500
    previous = (FollowedArtist(key="youtube:channel:" + artist["id"], name="Nora Velasco"),)
    result = collect_youtube_quickly(context(previous_followings=previous))
    assert result.status == "error" and result.followings is None
    assert len(result.checked["youtube:channel:" + artist["id"]].items) == 2


# --- youtube.toml et tri manuel -----------------------------------------------------------------


def test_fichier_de_tri_lu_et_reecrit(tmp_path) -> None:
    path = tmp_path / "youtube.toml"
    path.write_text(
        'artists = [\n    "@kid",  # Kid Marin\n]\nignore = [\n    "UC1",\n]\n', encoding="utf-8"
    )
    triage = TriageFile(path)
    triage.decide(Channel(id="UC1", title="Label Records"), follow=True)
    triage.decide(Channel(id="UC2", title="Kid Marin", handle="@kid"), follow=False)
    triage.save()
    text = path.read_text(encoding="utf-8")
    assert '"UC1",  # Label Records' in text and '"UC2",  # Kid Marin' in text
    config = load_config(tmp_path / "absent.toml", youtube_triage=path)
    assert (config.youtube.artists, config.youtube.ignore) == (("UC1",), ("UC2",))


@pytest.mark.parametrize(
    ("config_text", "triage_text"),
    [
        ("[youtube]\nignore = ['UC1']\n", ""),  # le tri vit dans youtube.toml
        ("", "artists = ['UC1']\nignore = ['uc1']\n"),
        ("", "autre = []\n"),
        ("", "artists = 'UC1'\n"),
    ],
)
def test_fichier_de_tri_invalide(tmp_path, config_text: str, triage_text: str) -> None:
    (tmp_path / "config.toml").write_text(config_text, encoding="utf-8")
    (tmp_path / "youtube.toml").write_text(triage_text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "config.toml", youtube_triage=tmp_path / "youtube.toml")


def test_tri_manuel_n_ecrit_que_les_reponses_utiles(subscriptions, tmp_path) -> None:
    path = tmp_path / "youtube.toml"
    answers = iter(["o"])  # la chaîne de sessions, seule chaîne douteuse
    status = youtube_triage.run(
        config=CONFIG,
        triage_path=path,
        state=None,
        env=YT_ENV,
        ask=lambda _prompt: next(answers),
        http=quick_http(),
    )
    assert status == 0
    triage = TriageFile(path)
    assert triage.entries == {"artists": {"UC" + "5".zfill(22): "Studio Sessions"}, "ignore": {}}
    # Revue complète : Entrée garde la proposition, sans rien écrire ; « n » corrige.
    answers = iter(["", "", "", "n", ""])  # Jeux, Kid Marin, Label, Nora, Studio (alphabétique)
    youtube_triage.run(
        config=load_config(tmp_path / "absent.toml", youtube_triage=path),
        triage_path=path,
        state=None,
        env=YT_ENV,
        review_all=True,
        ask=lambda _prompt: next(answers),
        http=quick_http(),
    )
    triage = TriageFile(path)
    assert triage.entries["ignore"] == {"UC" + "1".zfill(22): "Nora Velasco"}
    assert "Jeux" not in path.read_text(encoding="utf-8")
