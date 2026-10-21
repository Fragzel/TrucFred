"""Sources de données, une par plateforme."""

from newrel.sources import spotify
from newrel.sources.base import SourceSpec

SOURCES: dict[str, SourceSpec] = {
    spotify.PLATFORM: SourceSpec(required_env=spotify.REQUIRED_ENV, collect=spotify.collect),
}
