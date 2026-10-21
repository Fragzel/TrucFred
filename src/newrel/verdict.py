"""Verdict d'un run : ce qui doit faire passer le workflow au rouge, ou seulement avertir."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from newrel.config import Config
from newrel.models import State

Level = Literal["ok", "warning", "error"]
LABELS = {"spotify": "Spotify", "soundcloud": "SoundCloud"}
_RANK: dict[Level, int] = {"ok": 0, "warning": 1, "error": 2}


@dataclass
class Verdict:
    level: Level = "ok"
    messages: list[tuple[Level, str]] = field(default_factory=list)

    def add(self, level: Level, message: str) -> None:
        self.messages.append((level, message))
        if _RANK[level] > _RANK[self.level]:
            self.level = level


def evaluate(
    verdict: Verdict,
    state: State,
    *,
    platforms: list[str],
    warnings: list[str],
    env: Mapping[str, str],
    now: datetime,
    config: Config,
) -> Verdict:
    for platform in platforms:
        source = state.sources.get(platform)
        if source is None:
            continue
        label = LABELS.get(platform, platform)
        if source.status == "auth_expired":
            verdict.add("error", f"{label} : {source.message}")
        elif source.status == "error":
            # Une panne passagère n'alerte qu'au deuxième run raté d'affilée.
            level: Level = "error" if source.consecutive_failures >= 2 else "warning"
            verdict.add(
                level, f"{label} : {source.message} (échec n° {source.consecutive_failures})"
            )
        elif source.status == "partial":
            verdict.add("warning", f"{label} : {source.message}")
    for message in warnings[:20]:
        verdict.add("warning", message)
    if "spotify" in platforms:
        _spotify_token_age(verdict, env.get("SPOTIFY_AUTHORIZED_AT"), now, config)
    return verdict


def _spotify_token_age(
    verdict: Verdict, authorized_at: str | None, now: datetime, config: Config
) -> None:
    if not authorized_at:
        verdict.add(
            "warning",
            "variable SPOTIFY_AUTHORIZED_AT absente :"
            " impossible d'anticiper l'expiration du refresh token",
        )
        return
    try:
        when = datetime.fromisoformat(authorized_at)
    except ValueError:
        verdict.add("warning", f"SPOTIFY_AUTHORIZED_AT illisible : {authorized_at!r}")
        return
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age = (now - when).days
    message = (
        f"refresh token Spotify autorisé il y a {age} jours (il expire à 6 mois) :"
        " relance « uv run newrel auth spotify »"
    )
    if age >= config.token_error_days:
        verdict.add("error", message)
    elif age >= config.token_warn_days:
        verdict.add("warning", message)
