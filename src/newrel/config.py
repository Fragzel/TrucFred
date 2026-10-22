"""Configuration publique (config.toml, aliases.toml) et secrets locaux (.env.local)."""

from __future__ import annotations

import getpass
import os
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
class SoundCloudConfig:
    exclude: tuple[str, ...] = ()
    """Comptes suivis à ignorer (URN ou nom de profil dans l'URL) : labels, amis, curateurs…"""
    requests_per_second: float = 1.5
    tracks_limit: int = 20
    playlists_limit: int = 10
    max_pages: int = 3
    time_budget_minutes: float = 15.0
    max_retry_after_seconds: float = 120.0
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
    soundcloud: SoundCloudConfig = field(default_factory=SoundCloudConfig)


@dataclass(frozen=True)
class Aliases:
    """aliases.toml : décisions manuelles sur l'identité des artistes entre plateformes."""

    same: tuple[frozenset[str], ...] = ()
    """Groupes d'identifiants (spotify:artist:…, soundcloud:users:…) désignant un même artiste."""
    never: tuple[frozenset[str], ...] = ()
    """Paires d'homonymes à ne jamais fusionner."""


def _section[T](cls: type[T], values: dict[str, Any], name: str) -> T:
    allowed = {f.name for f in fields(cls)} - {"spotify", "soundcloud"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"[{name}] clé(s) inconnue(s) : {', '.join(unknown)}")
    for key in ("groups", "exclude"):
        if key in values:
            values = {**values, key: tuple(values[key])}
    return cls(**values)


def load_config(path: Path) -> Config:
    """Lit config.toml ; les clés absentes gardent leur valeur par défaut."""
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} : {exc}") from exc
    unknown = sorted(set(data) - {"general", "spotify", "soundcloud"})
    if unknown:
        raise ConfigError(f"{path} : section(s) inconnue(s) : {', '.join(unknown)}")

    spotify = _section(SpotifyConfig, data.get("spotify", {}), "spotify")
    bad_groups = sorted(set(spotify.groups) - SPOTIFY_GROUPS)
    if bad_groups or not spotify.groups:
        raise ConfigError(f"[spotify] groups invalides : {', '.join(bad_groups) or 'liste vide'}")
    soundcloud = _section(SoundCloudConfig, data.get("soundcloud", {}), "soundcloud")
    general = _section(Config, data.get("general", {}), "general")
    config = replace(general, spotify=spotify, soundcloud=soundcloud)
    try:
        ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[general] fuseau horaire inconnu : {config.timezone}") from exc
    return config


def load_aliases(path: Path) -> Aliases:
    """Lit aliases.toml : des listes [[same]] et [[never]] avec chacune une clé « keys »."""
    if not path.exists():
        return Aliases()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} : {exc}") from exc
    groups: dict[str, tuple[frozenset[str], ...]] = {}
    for section in ("same", "never"):
        entries = data.pop(section, [])
        if not all(
            isinstance(entry.get("keys"), list) and len(entry["keys"]) >= 2 for entry in entries
        ):
            raise ConfigError(
                f"{path} : chaque [[{section}]] doit avoir keys = [au moins 2 identifiants]"
            )
        groups[section] = tuple(frozenset(entry["keys"]) for entry in entries)
    if data:
        raise ConfigError(f"{path} : section(s) inconnue(s) : {', '.join(sorted(data))}")
    return Aliases(same=groups["same"], never=groups["never"])


def ask_env(name: str, *, hidden: bool = False, prompt: str | None = None) -> str:
    """Valeur prise dans l'environnement, sinon demandée au terminal (masquée pour un secret)."""
    value = os.environ.get(name, "").strip()
    while not value:
        value = (getpass.getpass if hidden else input)(f"{prompt or name} : ").strip()
    return value


def update_env_file(path: Path, values: dict[str, str]) -> None:
    """Écrit ou remplace des lignes KEY=VALUE dans un fichier local (ignoré par git)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in values]
    text = "\n".join([*kept, *(f"{key}={value}" for key, value in values.items())]) + "\n"
    path.write_text(text, encoding="utf-8")


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
