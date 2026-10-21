"""Modèles de données : état interne (state.json) et contrat public (releases.json)."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["spotify", "soundcloud"]
ReleaseType = Literal["album", "ep", "single", "track"]
Precision = Literal["year", "month", "day"]
Status = Literal["ok", "partial", "error", "auth_expired"]

SCHEMA_VERSION = 1


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Ce que renvoient les sources -------------------------------------------------------------


class ItemArtist(Model):
    key: str
    """Identifiant de plateforme, par exemple « spotify:artist:4Z8W4fKeB5YxbusRsdQVPb »."""
    name: str


class SourceItem(Model):
    """Une sortie telle qu'une plateforme la décrit (un « lien » une fois stockée)."""

    key: str
    """Par exemple « spotify:album:5Ir… » : sert de clé dans l'état."""
    platform: Platform
    id: str
    url: str
    title: str
    type: ReleaseType
    type_inferred: bool = False
    artists: list[ItemArtist]
    date: str
    precision: Precision
    tracks: int | None = None
    cover: str | None = None


class FollowedArtist(Model):
    key: str
    name: str


# --- state.json -------------------------------------------------------------------------------


class SourceState(Model):
    status: Status | None = None
    message: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    followings: list[FollowedArtist] = Field(default_factory=list)
    followings_at: datetime | None = None


class ArtistState(Model):
    name: str
    baseline_at: datetime
    """Première vérification : tout ce qui est trouvé ce jour-là est du catalogue (backfill)."""
    last_checked_at: datetime


class LinkState(Model):
    item: SourceItem
    first_seen: datetime
    last_seen: datetime
    backfill: bool
    via: list[str]
    """Artistes suivis par lesquels on a trouvé ce lien (disparaît avec le dernier)."""


class State(Model):
    schema_version: int = SCHEMA_VERSION
    sources: dict[str, SourceState] = Field(default_factory=dict)
    artists: dict[str, ArtistState] = Field(default_factory=dict)
    links: dict[str, LinkState] = Field(default_factory=dict)


# --- releases.json (lu par le site) -----------------------------------------------------------


class Artist(Model):
    id: str
    name: str


class Link(Model):
    platform: Platform
    url: str
    type: ReleaseType
    date: str
    precision: Precision


class Cover(Model):
    url: str
    platform: Platform
    """La pochette renvoie vers la plateforme dont elle vient."""


class Release(Model):
    id: str
    """Stable : dérivé du premier lien détecté, jamais recalculé."""
    title: str
    edition: str | None = None
    type: ReleaseType
    type_inferred: bool = False
    artists: list[Artist]
    date: str
    precision: Precision
    sort_date: date
    first_seen: datetime
    backfill: bool
    """Trouvée lors de la première vérification de l'artiste : pas de badge « Nouveau »."""
    tracks: int | None = None
    cover: Cover | None = None
    links: list[Link]


class SourceSummary(Model):
    status: Status | None = None
    message: str | None = None
    last_success_at: datetime | None = None
    followed: int = 0


class Rules(Model):
    new_days: int
    new_max_age_days: int
    stale_hours: int


class ReleasesFile(Model):
    schema_version: int = SCHEMA_VERSION
    generated_at: datetime
    timezone: str
    window_days: int
    rules: Rules
    sources: dict[str, SourceSummary]
    aliases: dict[str, str] = Field(default_factory=dict)
    """Ancien identifiant → identifiant actuel, quand deux sorties ont été fusionnées."""
    releases: list[Release]


def releases_schema() -> str:
    """Schéma JSON de releases.json, versionné dans schema/ comme contrat avec le front."""
    return json.dumps(ReleasesFile.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
