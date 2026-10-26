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
    quota_window_hours: float = 24.0
    active_within_days: int = 365
    active_interval_days: float = 2.0
    dormant_interval_days: float = 7.0
    full_check_days: int = 30
    tracklist_calls: int = 10
    """Titres des EP et albums : un appel par album, pris sur le budget du jour avant les
    artistes."""


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
    tracklist_calls: int = 50
    """Titres des playlists connues avant leur collecte : un appel par playlist, une seule fois."""


@dataclass(frozen=True)
class YouTubeConfig:
    requests_per_second: float = 3.0
    uploads_limit: int = 20
    """Dernières vidéos lues par chaîne (une page de playlistItems)."""
    min_duration_seconds: int = 60
    max_duration_minutes: int = 20
    """Au-delà : concert filmé, mix ou album complet plutôt qu'un clip."""
    time_budget_minutes: float = 15.0
    max_retry_after_seconds: float = 120.0
    artists: tuple[str, ...] = ()
    """Chaînes à suivre quoi qu'en dise le tri automatique (youtube.toml, pas config.toml)."""
    ignore: tuple[str, ...] = ()
    """Chaînes à ne jamais suivre (youtube.toml)."""


@dataclass(frozen=True)
class NotifyConfig:
    """Notification ntfy après un run qui trouve des nouveautés (secret NTFY_TOPIC)."""

    site_url: str = "https://fragzel.github.io/TrucFred/"
    types: tuple[str, ...] = ("album", "ep", "single", "track", "video")
    max_items: int = 10
    server: str = "https://ntfy.sh"


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
    schedule_time: str = "06:17"
    """Heure du cron dans .github/workflows/update.yml (à garder identiques)."""
    schedule_grace_minutes: int = 45
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    soundcloud: SoundCloudConfig = field(default_factory=SoundCloudConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)


SECTIONS = ("spotify", "soundcloud", "youtube", "notify")
RELEASE_TYPES = frozenset({"album", "ep", "single", "track", "video"})
TRIAGE_KEYS = ("artists", "ignore")


@dataclass(frozen=True)
class Aliases:
    """aliases.toml : décisions manuelles sur l'identité des artistes entre plateformes."""

    same: tuple[frozenset[str], ...] = ()
    """Groupes d'identifiants (spotify:artist:…, soundcloud:users:…) désignant un même artiste."""
    never: tuple[frozenset[str], ...] = ()
    """Paires d'homonymes à ne jamais fusionner."""


def _section[T](cls: type[T], values: dict[str, Any], name: str) -> T:
    allowed = {f.name for f in fields(cls)} - set(SECTIONS)
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"[{name}] clé(s) inconnue(s) : {', '.join(unknown)}")
    for key in ("groups", "exclude", "types"):
        if key in values:
            values = {**values, key: tuple(values[key])}
    return cls(**values)


def load_config(path: Path, *, youtube_triage: Path | None = None) -> Config:
    """Lit config.toml ; les clés absentes gardent leur valeur par défaut.

    Le tri des abonnements YouTube vient d'un fichier à part (youtube.toml), tenu par
    « newrel triage youtube ».
    """
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} : {exc}") from exc
    unknown = sorted(set(data) - {"general", *SECTIONS})
    if unknown:
        raise ConfigError(f"{path} : section(s) inconnue(s) : {', '.join(unknown)}")

    spotify = _section(SpotifyConfig, data.get("spotify", {}), "spotify")
    bad_groups = sorted(set(spotify.groups) - SPOTIFY_GROUPS)
    if bad_groups or not spotify.groups:
        raise ConfigError(f"[spotify] groups invalides : {', '.join(bad_groups) or 'liste vide'}")
    soundcloud = _section(SoundCloudConfig, data.get("soundcloud", {}), "soundcloud")
    youtube_values = data.get("youtube", {})
    if misplaced := sorted(set(youtube_values) & set(TRIAGE_KEYS)):
        raise ConfigError(f"[youtube] {', '.join(misplaced)} : à ranger dans youtube.toml")
    youtube = _section(YouTubeConfig, youtube_values, "youtube")
    if youtube_triage is not None:
        youtube = replace(youtube, **load_youtube_triage(youtube_triage))
    notify = _section(NotifyConfig, data.get("notify", {}), "notify")
    if bad_types := sorted(set(notify.types) - RELEASE_TYPES):
        raise ConfigError(f"[notify] types inconnus : {', '.join(bad_types)}")
    general = _section(Config, data.get("general", {}), "general")
    config = replace(
        general, spotify=spotify, soundcloud=soundcloud, youtube=youtube, notify=notify
    )
    try:
        ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[general] fuseau horaire inconnu : {config.timezone}") from exc
    hours, _, minutes = config.schedule_time.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60):
        raise ConfigError(
            f"[general] schedule_time attendu au format HH:MM : {config.schedule_time}"
        )
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


def load_youtube_triage(path: Path) -> dict[str, tuple[str, ...]]:
    """Lit youtube.toml : listes « artists » et « ignore » de chaînes (UC… ou @handle)."""
    if not path.exists():
        return {key: () for key in TRIAGE_KEYS}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} : {exc}") from exc
    if unknown := sorted(set(data) - set(TRIAGE_KEYS)):
        raise ConfigError(f"{path} : clé(s) inconnue(s) : {', '.join(unknown)}")
    lists: dict[str, tuple[str, ...]] = {}
    for key in TRIAGE_KEYS:
        values = data.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigError(f"{path} : {key} doit être une liste de chaînes (UC… ou @…)")
        lists[key] = tuple(value.strip() for value in values if value.strip())
    if both := sorted({v.lower() for v in lists["artists"]} & {v.lower() for v in lists["ignore"]}):
        raise ConfigError(f"{path} : à la fois dans artists et ignore : {', '.join(both)}")
    return lists


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
