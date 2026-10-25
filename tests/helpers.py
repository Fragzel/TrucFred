"""Constantes et raccourcis partagés par les tests."""

from datetime import UTC, date, datetime, timedelta

from newrel.config import Config, SoundCloudConfig, SpotifyConfig, YouTubeConfig
from newrel.http import HttpClient
from newrel.sources import soundcloud, spotify, youtube
from newrel.sources.base import SourceContext, SourceResult, SourceSpec

NOW = datetime(2026, 10, 22, 4, 17, tzinfo=UTC)  # un jeudi, run du matin
CUTOFF = date(2026, 10, 22) - timedelta(days=90)
ENV = {
    "SPOTIFY_CLIENT_ID": "client-id",
    "SPOTIFY_CLIENT_SECRET": "client-secret",
    "SPOTIFY_REFRESH_TOKEN": "refresh-token",
    "SPOTIFY_AUTHORIZED_AT": "2026-10-01T09:00:00Z",
}
SC_ENV = {
    "SOUNDCLOUD_CLIENT_ID": "sc-client-id",
    "SOUNDCLOUD_CLIENT_SECRET": "sc-client-secret",
    "SOUNDCLOUD_USER_URN": "soundcloud:users:1",
}
YT_ENV = {
    "YOUTUBE_API_KEY": "yt-key",
    "YOUTUBE_CHANNEL_ID": "UCami" + "0" * 19,  # la chaîne dont on lit les abonnements publics
}
CONFIG = Config(
    # Sans fenêtre de quota : les tests enchaînent des runs à 24 h d'intervalle tout pile.
    spotify=SpotifyConfig(requests_per_second=0, quota_window_hours=0),
    soundcloud=SoundCloudConfig(requests_per_second=0),
    youtube=YouTubeConfig(requests_per_second=0),
)


def quick_http() -> HttpClient:
    """Client sans débit limité ni attente réelle."""
    return HttpClient(requests_per_second=0, sleep=lambda _seconds: None)


def collect_quickly(ctx: SourceContext) -> SourceResult:
    return spotify.collect(ctx, http=quick_http())


def collect_soundcloud_quickly(ctx: SourceContext) -> SourceResult:
    return soundcloud.collect(ctx, http=quick_http())


def collect_youtube_quickly(ctx: SourceContext) -> SourceResult:
    return youtube.collect(ctx, http=quick_http())


SOURCES = {
    "spotify": SourceSpec(required_env=spotify.REQUIRED_ENV, collect=collect_quickly),
    "soundcloud": SourceSpec(
        required_env=soundcloud.REQUIRED_ENV, collect=collect_soundcloud_quickly
    ),
    "youtube": SourceSpec(required_env=youtube.REQUIRED_ENV, collect=collect_youtube_quickly),
}


def make_context(**overrides: object) -> SourceContext:
    values: dict[str, object] = {"config": CONFIG, "env": ENV, "now": NOW, "cutoff": CUTOFF}
    return SourceContext(**(values | overrides))  # type: ignore[arg-type]
