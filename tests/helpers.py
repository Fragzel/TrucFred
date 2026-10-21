"""Constantes et raccourcis partagés par les tests."""

from datetime import UTC, date, datetime, timedelta

from newrel.config import Config, SpotifyConfig
from newrel.http import HttpClient
from newrel.sources import spotify
from newrel.sources.base import SourceContext, SourceResult, SourceSpec

NOW = datetime(2026, 10, 22, 4, 17, tzinfo=UTC)  # un jeudi, run du matin
CUTOFF = date(2026, 10, 22) - timedelta(days=90)
ENV = {
    "SPOTIFY_CLIENT_ID": "client-id",
    "SPOTIFY_CLIENT_SECRET": "client-secret",
    "SPOTIFY_REFRESH_TOKEN": "refresh-token",
    "SPOTIFY_AUTHORIZED_AT": "2026-10-01T09:00:00Z",
}
CONFIG = Config(spotify=SpotifyConfig(requests_per_second=0))


def quick_http() -> HttpClient:
    """Client sans débit limité ni attente réelle."""
    return HttpClient(requests_per_second=0, sleep=lambda _seconds: None)


def collect_quickly(ctx: SourceContext) -> SourceResult:
    return spotify.collect(ctx, http=quick_http())


SOURCES = {"spotify": SourceSpec(required_env=spotify.REQUIRED_ENV, collect=collect_quickly)}


def make_context(**overrides: object) -> SourceContext:
    values: dict[str, object] = {"config": CONFIG, "env": ENV, "now": NOW, "cutoff": CUTOFF}
    return SourceContext(**(values | overrides))  # type: ignore[arg-type]
