"""Configuration publique (config.toml) et secrets locaux (.env.local)."""

from __future__ import annotations

import tomllib
from collections.abc import MutableMapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SPOTIFY_GROUPS = frozenset({"album", "single", "appears_on", "compilation"})


class ConfigError(Exception):
    """Configuration invalide ; le message s'adresse à l'utilisateur."""


@dataclass(frozen=True)
class SpotifyConfig:
    market: str = "FR"
    groups: tuple[str, ...] = ("album", "single")
    max_pages: int = 5
    requests_per_second: float = 2.0
    time_budget_minutes: float = 15.0
    max_retry_after_seconds: float = 120.0
    # Development Mode : environ 100 appels catalogue par 24 h, partagés entre toutes les apps
    # du compte développeur (mesuré le 22/10/2026, non documenté).
    daily_catalog_calls: int = 90
    active_within_days: int = 365
    active_interval_days: float = 2.0
    dormant_interval_days: float = 7.0
    full_check_days: int = 30


@dataclass(frozen=True)
class Config:
    timezone: str = "Europe/Paris"
    window_days: int = 90
    new_days: int = 7
    new_max_age_days: int = 14
    stale_hours: int = 36
    followings_drop_ratio: float = 0.3
    token_warn_days: int = 150
    token_error_days: int = 170
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)


def _section[T](cls: type[T], values: dict[str, Any], name: str) -> T:
    allowed = {f.name for f in fields(cls)} - {"spotify"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"[{name}] clé(s) inconnue(s) : {', '.join(unknown)}")
    if "groups" in values:
        values = {**values, "groups": tuple(values["groups"])}
    return cls(**values)


def load_config(path: Path) -> Config:
    """Lit config.toml ; les clés absentes gardent leur valeur par défaut."""
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} : {exc}") from exc
    unknown = sorted(set(data) - {"general", "spotify"})
    if unknown:
        raise ConfigError(f"{path} : section(s) inconnue(s) : {', '.join(unknown)}")

    spotify = _section(SpotifyConfig, data.get("spotify", {}), "spotify")
    bad_groups = sorted(set(spotify.groups) - SPOTIFY_GROUPS)
    if bad_groups or not spotify.groups:
        raise ConfigError(f"[spotify] groups invalides : {', '.join(bad_groups) or 'liste vide'}")
    config = replace(_section(Config, data.get("general", {}), "general"), spotify=spotify)
    try:
        ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[general] fuseau horaire inconnu : {config.timezone}") from exc
    return config


def load_env_file(path: Path, environ: MutableMapping[str, str]) -> None:
    """Charge les lignes KEY=VALUE d'un fichier local sans écraser l'environnement existant."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        environ.setdefault(key.strip(), value.strip())
