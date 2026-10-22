"""Dates partielles (« 2026 », « 2026-10 », « 2026-10-17 ») et date de tri."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from newrel.models import Precision

_FORMATS: dict[Precision, re.Pattern[str]] = {
    "day": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "month": re.compile(r"\d{4}-\d{2}"),
    "year": re.compile(r"\d{4}"),
}


def bounds(value: str, precision: Precision) -> tuple[date, date]:
    """Premier et dernier jour couverts par une date partielle (ValueError si invalide)."""
    if precision == "day":
        day = date.fromisoformat(value)
        return day, day
    if precision == "month":
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    year = int(value)
    return date(year, 1, 1), date(year, 12, 31)


def normalize(value: str | None, precision: str | None) -> tuple[str, Precision] | None:
    """Valide une date partielle ; déduit la précision du format quand elle ne correspond pas.

    Renvoie None pour une date inexploitable (Spotify renvoie parfois « 0000 »).
    """
    if not value:
        return None
    candidates: list[Precision] = [p for p in _FORMATS if p == precision]
    candidates += [p for p in _FORMATS if p != precision]
    for candidate in candidates:
        if _FORMATS[candidate].fullmatch(value):
            try:
                bounds(value, candidate)
            except ValueError:
                return None
            return value, candidate
    return None


def historical(
    value: str, precision: Precision, seen_day: date, baseline: bool, max_age_days: int
) -> bool:
    """Sortie de catalogue, sans badge « Nouveau » : trouvée au premier passage sur un artiste
    alors qu'elle avait déjà plus de max_age_days jours, ou qu'elle n'est datée qu'au mois ou à
    l'année (impossible de la situer). Une sortie récente reste une nouveauté même au premier
    passage.
    """
    if not baseline:
        return False
    if precision != "day":
        return True
    return date.fromisoformat(value) < seen_day - timedelta(days=max_age_days)


def sort_date(value: str, precision: Precision, first_seen: date, backfill: bool) -> date:
    """Date de tri : la date exacte si on l'a, sinon le jour de détection borné à la période."""
    start, end = bounds(value, precision)
    if precision == "day" or backfill:
        return start
    return min(max(first_seen, start), end)
