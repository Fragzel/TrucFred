"""Un run complet : sources → état → releases.json → site.

Une source en panne n'emporte pas les autres : elle garde ses données du run précédent.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from newrel import releases as releases_file
from newrel import site
from newrel.config import Aliases, Config
from newrel.models import ReleasesFile, SourceItem, State
from newrel.sources import SOURCES
from newrel.sources.base import SourceResult, SourceSpec
from newrel.state import apply_result, context_for, load_state, prune, save_state
from newrel.verdict import LABELS, Verdict, evaluate

log = logging.getLogger(__name__)


class FatalError(Exception):
    """Arrête le run sans rien écrire (état illisible…)."""


@dataclass
class SourceReport:
    platform: str
    status: str
    message: str | None
    calls: int
    checked: int
    pending: int
    new_links: int
    new_releases: list[SourceItem] = field(default_factory=list)


@dataclass
class RunOutcome:
    releases: ReleasesFile
    verdict: Verdict
    state_written: bool
    reports: list[SourceReport] = field(default_factory=list)


def run(
    *,
    config: Config,
    state_dir: Path,
    out_dir: Path,
    site_dir: Path,
    env: Mapping[str, str],
    offline: bool = False,
    accept_drop: bool = False,
    now: datetime | None = None,
    sources: Mapping[str, SourceSpec] | None = None,
    aliases: Aliases | None = None,
) -> RunOutcome:
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    sources = SOURCES if sources is None else sources
    cutoff = now.astimezone(ZoneInfo(config.timezone)).date() - timedelta(days=config.window_days)
    state_path = state_dir / "state.json"
    try:
        previous = load_state(state_path)
    except ValueError as exc:  # ValidationError de pydantic hérite de ValueError
        raise FatalError(f"{state_path} illisible, rien n'a été écrit : {exc}") from exc
    state = previous or State()
    configured = {
        name: spec
        for name, spec in sources.items()
        if all(env.get(var) for var in spec.required_env)
    }
    verdict = Verdict()
    reports: list[SourceReport] = []
    warnings: list[str] = []

    if not offline:
        for name, spec in sources.items():
            missing = [var for var in spec.required_env if not env.get(var)]
            if missing:
                label = LABELS.get(name, name)
                verdict.add(
                    "warning", f"{label} non configuré (secrets absents : {', '.join(missing)})"
                )
        if configured and previous is None:
            # Sans état, tout part en catalogue (backfill) : aucune fausse nouveauté.
            verdict.add(
                "warning",
                "aucun état précédent : démarrage à zéro, sorties actuelles en historique",
            )
        for name, spec in configured.items():
            context = context_for(
                state, name, config=config, env=env, now=now, cutoff=cutoff, accept_drop=accept_drop
            )
            try:
                result = spec.collect(context)
            except Exception as exc:
                log.exception("source %s : erreur inattendue", name)
                result = SourceResult(
                    platform=name,
                    status="error",
                    message=f"erreur inattendue ({type(exc).__name__})",
                )
            stats = apply_result(state, result, now=now, cutoff=cutoff)
            warnings += result.warnings
            reports.append(
                SourceReport(
                    platform=name,
                    status=result.status,
                    message=result.message,
                    calls=result.calls,
                    checked=len(result.checked),
                    pending=result.pending,
                    new_links=stats.new_links,
                    new_releases=stats.new_releases,
                )
            )
        prune(state, cutoff)

    state_written = not offline and bool(configured)
    generated_at = now if state_written else _last_update(state, now)
    data = releases_file.build(
        state, config, generated_at=generated_at, now=now, artist_aliases=aliases
    )
    payload = data.model_dump_json(indent=2) + "\n"
    if state_written:
        save_state(state, state_path)
        (state_dir / "releases.json").write_text(payload, encoding="utf-8")
    site.build(site_dir, out_dir, payload)
    if not offline:
        evaluate(
            verdict,
            state,
            platforms=list(configured),
            warnings=warnings,
            env=env,
            now=now,
            config=config,
        )
    return RunOutcome(releases=data, verdict=verdict, state_written=state_written, reports=reports)


def _last_update(state: State, now: datetime) -> datetime:
    """Reconstruction hors ligne : la page garde la date de la dernière vraie collecte."""
    attempts = [
        source.last_attempt_at for source in state.sources.values() if source.last_attempt_at
    ]
    return max(attempts, default=now)
