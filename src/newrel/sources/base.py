"""Contrat commun des sources : ce qu'elles reçoivent et ce qu'elles renvoient."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from newrel.config import Config
from newrel.models import FollowedArtist, SourceItem, Status

SEVERITY: dict[Status, int] = {"ok": 0, "partial": 1, "error": 2, "auth_expired": 3}


@dataclass(frozen=True)
class SourceContext:
    """Vue en lecture seule de l'état, utile à une source pendant un run."""

    config: Config
    env: Mapping[str, str]
    now: datetime
    cutoff: date
    known_links: frozenset[str] = frozenset()
    baselined_artists: frozenset[str] = frozenset()
    last_checked: Mapping[str, datetime] = field(default_factory=dict)
    previous_followings: tuple[FollowedArtist, ...] = ()
    accept_drop: bool = False


@dataclass
class SourceResult:
    platform: str
    status: Status = "ok"
    message: str | None = None
    followings: list[FollowedArtist] | None = None
    """Nouvelle liste d'abonnements, ou None pour garder la précédente."""
    checked: dict[str, list[SourceItem]] = field(default_factory=dict)
    """Artistes vérifiés pendant ce run, avec les sorties trouvées."""
    warnings: list[str] = field(default_factory=list)
    calls: int = 0

    def degrade(self, status: Status, message: str) -> None:
        """Retient le statut le plus grave ; les autres problèmes deviennent des avertissements."""
        if SEVERITY[status] > SEVERITY[self.status]:
            self.status, self.message = status, message
        else:
            self.warnings.append(message)


@dataclass(frozen=True)
class SourceSpec:
    required_env: tuple[str, ...]
    collect: Callable[[SourceContext], SourceResult]


def followings_guard(
    new: list[FollowedArtist],
    previous: tuple[FollowedArtist, ...],
    max_drop: float,
    accept_drop: bool,
) -> str | None:
    """Message d'erreur si la liste reçue paraît anormale : vide ou en chute brutale."""
    if accept_drop or not previous:
        return None
    if not new:
        return f"0 abonnement reçu contre {len(previous)} au run précédent : liste ignorée"
    if len(new) < len(previous) * (1 - max_drop):
        return (
            f"{len(new)} abonnements reçus contre {len(previous)} au run précédent : liste ignorée"
            " (relance avec accept_drop si la baisse est voulue)"
        )
    return None
