"""Sources de données, une par plateforme."""

from newrel.sources import soundcloud, spotify
from newrel.sources.base import SourceSpec

SOURCES: dict[str, SourceSpec] = {
    spotify.PLATFORM: SourceSpec(required_env=spotify.REQUIRED_ENV, collect=spotify.collect),
    soundcloud.PLATFORM: SourceSpec(
        required_env=soundcloud.REQUIRED_ENV, collect=soundcloud.collect
    ),
}
