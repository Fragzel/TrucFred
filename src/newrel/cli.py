"""Ligne de commande : « uv run newrel <commande> »."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from newrel import __version__, dates, pipeline, site
from newrel.config import ConfigError, load_config, load_env_file
from newrel.models import State, releases_schema
from newrel.sources import SOURCES
from newrel.state import context_for, load_state
from newrel.verdict import LABELS

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument(
        "--state-dir", type=Path, default=Path("data"), help="état (worktree de la branche data)"
    )


def _site_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--site", type=Path, default=Path("site"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newrel", description="Nouvelles sorties des artistes suivis."
    )
    parser.add_argument("--version", action="version", version=f"newrel {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="collecte, met à jour l'état et construit le site")
    _common(run)
    _site_paths(run)
    run.add_argument(
        "--offline", action="store_true", help="reconstruit le site sans appeler les API"
    )
    run.add_argument(
        "--accept-drop",
        action="store_true",
        help="accepte une forte baisse du nombre d'abonnements",
    )

    fetch = commands.add_parser("fetch", help="interroge une source à blanc, sans rien écrire")
    fetch.add_argument("source", choices=sorted(SOURCES))
    _common(fetch)

    auth = commands.add_parser(
        "auth", help="autorisation OAuth locale (Spotify : tous les ~6 mois)"
    )
    auth.add_argument("source", choices=["spotify"])
    auth.add_argument("--port", type=int, default=8888)
    auth.add_argument("--no-gh", action="store_true", help="n'enregistre pas les secrets avec gh")
    auth.add_argument("--repo", help="dépôt GitHub cible (par défaut : celui du dossier courant)")
    auth.add_argument(
        "--write-env", action="store_true", help="écrit aussi les valeurs dans .env.local"
    )

    serve = commands.add_parser("serve", help="sert le site en local (données de data/ ou exemple)")
    _common(serve)
    _site_paths(serve)
    serve.add_argument("--port", type=int, default=8000)

    schema = commands.add_parser("schema", help="régénère le schéma JSON de releases.json")
    schema.add_argument("--out", type=Path, default=Path("schema/releases.schema.json"))
    return parser


def _annotate(level: str, message: str) -> None:
    if IN_ACTIONS:
        print(f"::{level}::{message}", flush=True)
    else:
        print(f"[{'erreur' if level == 'error' else 'avertissement'}] {message}")


def _github_file(variable: str, text: str) -> None:
    if path := os.environ.get(variable):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def _summary(outcome: pipeline.RunOutcome) -> str:
    lines = ["## Collecte", "", "| Source | Statut | Appels | Artistes vérifiés | Nouveautés |"]
    lines.append("|---|---|---|---|---|")
    for report in outcome.reports:
        label = LABELS.get(report.platform, report.platform)
        lines.append(
            f"| {label} | {report.status} | {report.calls} | {report.checked}"
            f" | {len(report.new_releases)} |"
        )
    if not outcome.reports:
        lines.append("| — | aucune collecte | | | |")
    lines += ["", f"{len(outcome.releases.releases)} sorties publiées sur la page.", ""]
    for level, message in outcome.verdict.messages:
        lines.append(f"- {'🔴' if level == 'error' else '🟡'} {message}")
    news = [item for report in outcome.reports for item in report.new_releases]
    if news:
        lines += ["", "### Nouveautés détectées", ""]
        for item in news[:30]:
            artists = ", ".join(artist.name for artist in item.artists)
            lines.append(f"- {item.date} · {item.type} · {artists} : [{item.title}]({item.url})")
    return "\n".join(lines) + "\n"


def _cmd_run(args: argparse.Namespace) -> int:
    outcome = pipeline.run(
        config=load_config(args.config),
        state_dir=args.state_dir,
        out_dir=args.out,
        site_dir=args.site,
        env=os.environ,
        offline=args.offline,
        accept_drop=args.accept_drop,
    )
    for report in outcome.reports:
        label = LABELS.get(report.platform, report.platform)
        print(
            f"{label} : {report.status}, {report.calls} appels, {report.checked} artistes vérifiés,"
            f" {report.new_links} liens ajoutés dont {len(report.new_releases)} nouveautés"
        )
    print(f"{len(outcome.releases.releases)} sorties publiées, verdict : {outcome.verdict.level}")
    for level, message in outcome.verdict.messages:
        _annotate(level, message)
    _github_file(
        "GITHUB_OUTPUT",
        f"level={outcome.verdict.level}\nstate_written={str(outcome.state_written).lower()}\n",
    )
    _github_file("GITHUB_STEP_SUMMARY", _summary(outcome))
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    spec = SOURCES[args.source]
    missing = [var for var in spec.required_env if not os.environ.get(var)]
    if missing:
        print(
            f"Secrets absents : {', '.join(missing)} (voir README, ou .env.local)", file=sys.stderr
        )
        return 2
    state = load_state(args.state_dir / "state.json") or State()
    now = datetime.now(UTC).replace(microsecond=0)
    cutoff = now.astimezone(ZoneInfo(config.timezone)).date() - timedelta(days=config.window_days)
    context = context_for(
        state, args.source, config=config, env=os.environ, now=now, cutoff=cutoff, accept_drop=True
    )
    result = spec.collect(context)
    print(f"Statut : {result.status}{f' ({result.message})' if result.message else ''}")
    followed = len(result.followings) if result.followings is not None else "inchangés"
    checked = len(result.checked)
    print(f"Abonnements : {followed} · artistes vérifiés : {checked} · appels : {result.calls}")
    for warning in result.warnings:
        print(f"[avertissement] {warning}")
    items = {
        item.key: item
        for items in result.checked.values()
        for item in items
        if dates.bounds(item.date, item.precision)[1] >= cutoff
    }
    print(f"\n{len(items)} sorties dans la fenêtre de {config.window_days} jours :")
    for item in sorted(items.values(), key=lambda item: item.date, reverse=True)[:60]:
        flag = "nouveau" if item.key not in context.known_links else "connu  "
        artists = ", ".join(artist.name for artist in item.artists)
        print(f"  {item.date:<10}  {flag}  {item.type:<6}  {artists} — {item.title}")
    return 1 if result.status in ("error", "auth_expired") else 0


def _cmd_auth(args: argparse.Namespace) -> int:
    from newrel.sources.spotify_auth import authorize

    env_file = Path(".env.local") if args.write_env else None
    return authorize(port=args.port, use_gh=not args.no_gh, repo=args.repo, env_file=env_file)


def _cmd_serve(args: argparse.Namespace) -> int:
    source = args.state_dir / "releases.json"
    if not source.exists():
        print(f"{source} introuvable : affichage des données d'exemple (site/sample.json).")
        source = args.site / "sample.json"
    site.build(args.site, args.out, source.read_text(encoding="utf-8"))
    site.serve(args.out, args.port)
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(releases_schema(), encoding="utf-8")
    print(f"Schéma écrit dans {args.out}")
    return 0


COMMANDS = {
    "run": _cmd_run,
    "fetch": _cmd_fetch,
    "auth": _cmd_auth,
    "serve": _cmd_serve,
    "schema": _cmd_schema,
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Sortie redirigée sous Windows (cp1252) : on remplace plutôt que de planter.
        stream.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx journalise chaque requête en INFO : une ligne par appel dans les logs publics.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not IN_ACTIONS:
        load_env_file(Path(".env.local"), os.environ)
    try:
        return COMMANDS[args.command](args)
    except (ConfigError, pipeline.FatalError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
