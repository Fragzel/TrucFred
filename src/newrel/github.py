"""Secrets et variables GitHub via la CLI gh. Les valeurs ne passent jamais en argument."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from newrel.config import update_env_file


def available() -> bool:
    return shutil.which("gh") is not None


def _gh(args: list[str], *, stdin: str | None = None, token: str | None = None) -> bool:
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    try:
        completed = subprocess.run(
            ["gh", *args],
            input=stdin,
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=60,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def set_secret(name: str, value: str, *, repo: str | None = None, token: str | None = None) -> bool:
    """La valeur passe par l'entrée standard : ni ligne de commande, ni log."""
    args = ["secret", "set", name, *(["--repo", repo] if repo else [])]
    return _gh(args, stdin=value, token=token)


def secret_names(repo: str | None = None) -> set[str] | None:
    """Noms des secrets du dépôt (GitHub n'en rend jamais la valeur) ; None en cas d'échec."""
    args = ["secret", "list", "--json", "name", "--jq", ".[].name"]
    try:
        completed = subprocess.run(
            ["gh", *args, *(["--repo", repo] if repo else [])],
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return set(completed.stdout.split()) if completed.returncode == 0 else None


def set_variable(name: str, value: str, *, repo: str | None = None) -> bool:
    args = ["variable", "set", name, "--body", value, *(["--repo", repo] if repo else [])]
    return _gh(args)


def save_settings(
    *,
    secrets: dict[str, str],
    variables: dict[str, str],
    use_gh: bool,
    repo: str | None,
    env_file: Path | None,
) -> int:
    """Fin des commandes « newrel auth » : secrets et variables du dépôt, .env.local au besoin."""
    status = 0
    names = ", ".join([*secrets, *variables])
    if use_gh and not available():
        print("gh introuvable : enregistre les secrets à la main (voir README).")
        status = 1
    elif use_gh:
        saved = [set_secret(name, value, repo=repo) for name, value in secrets.items()]
        saved += [set_variable(name, value, repo=repo) for name, value in variables.items()]
        if all(saved):
            print(f"Enregistrés dans le dépôt : {names}.")
        else:
            print(
                "Échec de l'enregistrement via gh : vérifie « gh auth status » et le dépôt ciblé."
            )
            status = 1
    if env_file:
        update_env_file(env_file, {**secrets, **variables})
        print(f"Valeurs écrites dans {env_file} (ignoré par git) pour les runs locaux.")
    return status
