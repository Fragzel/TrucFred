import httpx
import pytest

from newrel.sources import youtube_auth
from newrel.sources.youtube import API_URL
from tests.helpers import YT_ENV
from tests.youtube_fake import yt_channel


@pytest.fixture
def friend(fake_youtube, monkeypatch):
    """La chaîne de l'ami, trouvée par son handle, avec deux abonnements publics."""
    monkeypatch.setenv("YOUTUBE_API_KEY", YT_ENV["YOUTUBE_API_KEY"])
    channel = yt_channel(0, "Fred", topics=(), handle="@fred")
    channel["id"] = YT_ENV["YOUTUBE_CHANNEL_ID"]
    fake_youtube.subscribe(channel, yt_channel(1, "Nora Velasco"))
    return fake_youtube


def test_cle_et_chaine_verifiees_puis_enregistrees(friend, tmp_path, capsys) -> None:
    env_file = tmp_path / ".env.local"
    status = youtube_auth.setup(
        profile="https://www.youtube.com/@Fred", use_gh=False, env_file=env_file
    )
    assert status == 0
    saved = env_file.read_text(encoding="utf-8")
    assert "YOUTUBE_API_KEY=yt-key" in saved
    assert f"YOUTUBE_CHANNEL_ID={YT_ENV['YOUTUBE_CHANNEL_ID']}" in saved
    assert "2 abonnements lisibles" in capsys.readouterr().out


def test_abonnements_prives_rien_d_enregistre(friend, tmp_path, capsys) -> None:
    friend.subscriptions_private = True
    env_file = tmp_path / ".env.local"
    status = youtube_auth.setup(profile="@fred", use_gh=False, env_file=env_file)
    assert status == 1
    assert "Garder tous mes abonnements privés" in capsys.readouterr().out
    assert not env_file.exists()


def test_cle_refusee(router, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "mauvaise-cle")
    refusal = {
        "error": {
            "code": 400,
            "errors": [{"reason": "badRequest"}],
            "details": [{"reason": "API_KEY_INVALID"}],
        }
    }
    router.get(f"{API_URL}/channels").mock(return_value=httpx.Response(400, json=refusal))
    status = youtube_auth.setup(profile="@fred", use_gh=False, env_file=tmp_path / ".env.local")
    out = capsys.readouterr().out
    assert status == 1 and "API_KEY_INVALID" in out
    # Sous GitHub Actions, « ::add-mask:: » demande justement de masquer la clé dans les logs.
    shown = [line for line in out.splitlines() if not line.startswith("::add-mask::")]
    assert not any("mauvaise-cle" in line for line in shown)


def test_chaine_sans_abonnement_visible_rien_d_enregistre(
    fake_youtube, monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", YT_ENV["YOUTUBE_API_KEY"])
    channel = yt_channel(0, "Fred", topics=(), handle="@fred")
    channel["id"] = YT_ENV["YOUTUBE_CHANNEL_ID"]
    fake_youtube.subscribe(channel)
    fake_youtube.subscribed_hidden = True
    env_file = tmp_path / ".env.local"
    assert youtube_auth.setup(profile="@fred", use_gh=False, env_file=env_file) == 1
    assert "aucun abonnement visible" in capsys.readouterr().out
    assert not env_file.exists()
