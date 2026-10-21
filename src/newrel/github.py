"""Secrets et variables GitHub via la CLI gh. Les valeurs ne passent jamais en argument."""

from __future__ import annotations

import os
import shutil
import subprocess


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


def set_variable(name: str, value: str, *, repo: str | None = None) -> bool:
    args = ["variable", "set", name, "--body", value, *(["--repo", repo] if repo else [])]
    return _gh(args)
