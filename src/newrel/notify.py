"""Notification push via ntfy.sh quand un run trouve de vraies nouveautés.

Le nom du canal (NTFY_TOPIC) fait office de mot de passe : sur ntfy.sh, quiconque le connaît
peut lire les messages. Il est donc tiré au hasard et rangé dans les secrets du dépôt.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from newrel import github
from newrel.config import NotifyConfig
from newrel.http import HttpClient, HttpError, ensure_ok, mask
from newrel.models import Release, ReleasesFile

TYPE_LABELS = {"album": "album", "ep": "EP", "single": "single", "track": "son", "video": "vidéo"}


def fresh_releases(data: ReleasesFile, now: datetime, config: NotifyConfig) -> list[Release]:
    """Sorties apparues pendant ce run, hors catalogue et hors types écartés.

    Une sortie déjà vue sur une autre plateforme garde sa première date de détection :
    elle n'est donc pas notifiée une deuxième fois.
    """
    return [
        release
        for release in data.releases
        if release.first_seen == now and not release.backfill and release.type in config.types
    ]


def payload(releases: list[Release], config: NotifyConfig) -> dict[str, Any]:
    lines = [
        f"{', '.join(artist.name for artist in release.artists[:2])} — {release.title}"
        f" ({TYPE_LABELS.get(release.type, release.type)})"
        for release in releases[: config.max_items]
    ]
    if len(releases) > config.max_items:
        lines.append(f"… et {len(releases) - config.max_items} autre(s) sur la page")
    count = len(releases)
    plural = "s" if count > 1 else ""
    return {
        "title": f"{count} nouvelle{plural} sortie{plural}",
        "message": "\n".join(lines),
        "click": config.site_url,
        "tags": ["musical_note"],
    }


def send(message: dict[str, Any], env: Mapping[str, str], config: NotifyConfig) -> None:
    """Publie un message JSON sur le serveur ntfy ; HttpError en cas de refus."""
    topic = env["NTFY_TOPIC"]
    mask(topic)
    headers = {"Authorization": f"Bearer {env['NTFY_TOKEN']}"} if env.get("NTFY_TOKEN") else {}
    with HttpClient(requests_per_second=0, retries=2) as client:
        response = client.request(
            "POST", config.server.rstrip("/"), json={"topic": topic, **message}, headers=headers
        )
    ensure_ok(response, "notification ntfy")


def setup(
    *,
    config: NotifyConfig,
    topic: str | None = None,
    use_gh: bool = True,
    repo: str | None = None,
    env_file: Path | None = None,
) -> int:
    """Mise en route : canal tiré au hasard, abonnement dans l'app ntfy, message de test."""
    topic = topic or f"nouvelles-sorties-{secrets.token_urlsafe(16)}"
    print(
        "1. Installe l'app ntfy (Android, iOS, ou https://ntfy.sh/app dans un navigateur).\n"
        f"2. Abonne-toi au sujet suivant, sur le serveur {config.server} :\n\n   {topic}\n\n"
        "   Garde-le pour toi : quiconque le connaît peut lire ces notifications."
    )
    input("3. Une fois abonné, appuie sur Entrée pour recevoir un message de test… ")
    test = {
        "title": "Nouvelles sorties",
        "message": "Notifications activées : un message arrivera après chaque run qui trouve"
        " des nouveautés.",
        "click": config.site_url,
        "tags": ["musical_note"],
    }
    try:
        send(test, {"NTFY_TOPIC": topic}, config)
    except HttpError as exc:
        print(f"Échec de l'envoi : {exc}")
        return 1
    print("Message de test envoyé.")
    return github.save_settings(
        secrets={"NTFY_TOPIC": topic}, variables={}, use_gh=use_gh, repo=repo, env_file=env_file
    )
