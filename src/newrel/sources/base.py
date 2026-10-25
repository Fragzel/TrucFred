"""Contrat commun des sources : ce qu'elles reçoivent et ce qu'elles renvoient."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from newrel.config import Config
from newrel.models import ArtistState, FollowedArtist, SourceItem, Status

SEVERITY: dict[Status, int] = {"ok": 0, "partial": 1, "error": 2, "auth_expired": 3}


@dataclass(frozen=True)
class SourceContext:
    """Vue en lecture seule de l'état, utile à une source pendant un run."""

    config: Config
    env: Mapping[str, str]
    now: datetime
    cutoff: date
    known_links: frozenset[str] = frozenset()
    artists: Mapping[str, ArtistState] = field(default_factory=dict)
    """Artistes déjà vérifiés au moins une fois (absents : premier passage, donc baseline)."""
    previous_followings: tuple[FollowedArtist, ...] = ()
    quota_reset_at: datetime | None = None
    catalog_used_at: datetime | None = None
    """Dernier run qui a interrogé le catalogue (début de la fenêtre de quota en cours)."""
    peer_names: frozenset[str] = frozenset()
    """Noms des artistes suivis sur les autres plateformes (indice pour le tri YouTube)."""
    accept_drop: bool = False


@dataclass
class ArtistCheck:
    """Vérification d'un artiste : sorties trouvées et repères pour le prochain passage."""

    items: list[SourceItem] = field(default_factory=list)
    catalog_total: int | None = None
    latest_release: date | None = None
    full: bool = True
    """Lecture détaillée ; False quand seul le total a été relu (inchangé)."""


@dataclass
class SourceResult:
    platform: str
    status: Status = "ok"
    message: str | None = None
    followings: list[FollowedArtist] | None = None
    """Nouvelle liste d'abonnements, ou None pour garder la précédente."""
    checked: dict[str, ArtistCheck] = field(default_factory=dict)
    """Artistes vérifiés pendant ce run."""
    pending: int = 0
    """Artistes laissés pour un prochain run (budget d'appels atteint)."""
    quota_reset_at: datetime | None = None
    catalog_used_at: datetime | None = None
    """Renseigné quand ce run a interrogé le catalogue : la fenêtre de quota repart d'ici."""
    next_check_at: datetime | None = None
    """Moment où la source pourra de nouveau interroger son catalogue (None : à chaque run)."""
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
