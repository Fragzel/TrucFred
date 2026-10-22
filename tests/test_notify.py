import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from newrel import notify, pipeline
from newrel.config import ConfigError, NotifyConfig, load_config
from newrel.models import Artist, Link, Release, ReleasesFile, Rules
from tests.helpers import CONFIG, ENV, NOW, SOURCES
from tests.spotify_fake import album

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
NTFY = {"NTFY_TOPIC": "nouvelles-sorties-test"}


def release(title: str, *, kind: str = "single", seen=NOW, backfill: bool = False) -> Release:
    return Release(
        id=f"r_{title}",
        title=title,
        type=kind,
        artists=[Artist(id="a_1", name="Nora Velasco")],
        date="2026-10-21",
        precision="day",
        sort_date="2026-10-21",
        first_seen=seen,
        backfill=backfill,
        links=[
            Link(
                platform="spotify",
                url="https://open.spotify.com/album/x",
                type=kind,
                date="2026-10-21",
                precision="day",
            )
        ],
    )


def data(*releases: Release) -> ReleasesFile:
    rules = Rules(new_days=7, new_max_age_days=14, stale_hours=36)
    return ReleasesFile(
        generated_at=NOW,
        timezone="Europe/Paris",
        window_days=90,
        rules=rules,
        sources={},
        releases=list(releases),
    )


def test_seules_les_vraies_nouveautes_du_run_sont_notifiees() -> None:
    releases = data(
        release("Neuf"),
        release("Hier", seen=NOW - timedelta(days=1)),
        release("Catalogue", backfill=True),
        release("Son", kind="track"),
    )
    assert [r.title for r in notify.fresh_releases(releases, NOW, NotifyConfig())] == [
        "Neuf",
        "Son",
    ]
    no_tracks = NotifyConfig(types=("album", "ep", "single"))
    assert [r.title for r in notify.fresh_releases(releases, NOW, no_tracks)] == ["Neuf"]


def test_message_resume_et_tronque() -> None:
    config = NotifyConfig(max_items=2)
    message = notify.payload([release("A"), release("B", kind="ep"), release("C")], config)
    assert message["title"] == "3 nouvelles sorties"
    assert message["message"].splitlines() == [
        "Nora Velasco — A (single)",
        "Nora Velasco — B (EP)",
        "… et 1 autre(s) sur la page",
    ]
    assert message["click"] == "https://fragzel.github.io/TrucFred/"
    assert notify.payload([release("Seul")], config)["title"] == "1 nouvelle sortie"


@pytest.fixture
def ntfy(router):
    return router.post(url__regex=r"https://ntfy\.sh/?$").mock(return_value=httpx.Response(200))


def run(tmp_path: Path, now=NOW, env=None):
    return pipeline.run(
        config=CONFIG,
        state_dir=tmp_path / "data",
        out_dir=tmp_path / "_site",
        site_dir=SITE_DIR,
        env=env or (ENV | NTFY),
        now=now,
        sources=SOURCES,
    )


def test_notification_apres_un_run_avec_nouveautes(tmp_path, fake_spotify, ntfy) -> None:
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.publish(
        "A1", "album", album("l1", "Échos", "2026-09-01", album_type="album", tracks=9)
    )
    run(tmp_path)  # premier passage : rien de récent, donc pas de notification
    assert ntfy.call_count == 0
    fake_spotify.publish("A1", "single", album("s1", "Lumières froides", "2026-10-23"))
    outcome = run(tmp_path, now=NOW + timedelta(days=1))
    assert (ntfy.call_count, outcome.notified) == (1, 1)
    sent = json.loads(ntfy.calls[0].request.content)
    assert sent["topic"] == "nouvelles-sorties-test"
    assert (sent["title"], sent["message"]) == (
        "1 nouvelle sortie",
        "Artiste Un — Lumières froides (single)",
    )


def test_notification_ratee_ne_fait_pas_echouer_le_run(tmp_path, fake_spotify, ntfy) -> None:
    ntfy.mock(return_value=httpx.Response(400))
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.publish("A1", "single", album("s1", "Lumières froides", "2026-10-21"))
    outcome = run(tmp_path)
    assert outcome.state_written and outcome.notified == 0
    assert any("notification non envoyée" in message for _, message in outcome.verdict.messages)


def test_pas_de_notification_sans_secret(tmp_path, fake_spotify, ntfy) -> None:
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.publish("A1", "single", album("s1", "Lumières froides", "2026-10-21"))
    run(tmp_path, env=ENV)
    assert ntfy.call_count == 0


def test_types_de_notification_configurables(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[notify]\ntypes = ["album", "chanson"]\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
    path.write_text('[notify]\ntypes = ["album"]\n', encoding="utf-8")
    assert load_config(path).notify == replace(NotifyConfig(), types=("album",))
