"""Mise en route YouTube (une fois) : vérifie la clé API et la chaîne, puis enregistre tout.

Aucune autorisation OAuth : les abonnements de la chaîne sont publics, une clé API suffit pour
les lire. La commande vérifie justement qu'ils le sont, puis enregistre la clé et l'identifiant
de la chaîne dans le dépôt.
"""

from __future__ import annotations

from pathlib import Path

from newrel import github
from newrel.config import ask_env
from newrel.http import HttpClient, HttpError
from newrel.sources.youtube import PrivateSubscriptions, YouTubeApi


def setup(
    *,
    profile: str | None,
    use_gh: bool = True,
    repo: str | None = None,
    env_file: Path | None = None,
) -> int:
    api_key = ask_env("YOUTUBE_API_KEY", hidden=True, prompt="Clé API YouTube (saisie masquée)")
    profile = profile or ask_env(
        "YOUTUBE_CHANNEL_URL",
        prompt=(
            "Chaîne du compte abonné aux artistes, pas celle d'un artiste"
            " (youtube.com/@…, @handle ou UC…)"
        ),
    )
    with HttpClient(requests_per_second=5) as client:
        api = YouTubeApi(client, api_key)
        try:
            channel = api.find_channel(profile)
            if channel is None:
                print(f"Échec : aucune chaîne YouTube trouvée pour « {profile} ».")
                return 1
            print(f"Chaîne trouvée : {channel.title} ({channel.id}).")
            total = api.subscription_count(channel.id)
        except PrivateSubscriptions as exc:
            print(f"Échec : {exc}, puis relance la commande.")
            return 1
        except HttpError as exc:
            print(f"Échec : {exc}.")
            if "API_KEY_INVALID" in str(exc):
                print("Clé API refusée : vérifie-la dans API et services > Identifiants.")
            elif "SERVICE_DISABLED" in str(exc) or "accessNotConfigured" in str(exc):
                print("Active « YouTube Data API v3 » dans la bibliothèque d'API du projet Google.")
            return 1
    if not total:
        print(
            "Échec : aucun abonnement visible sur cette chaîne, rien n'a été enregistré.\n"
            "- Le réglage « Garder tous mes abonnements privés » est-il bien décoché, et enregistré"
            " ?\n- Les abonnements sont-ils sur cette chaîne ? Un compte Google peut en avoir"
            " plusieurs (avatar > Changer de compte) : il faut celle qui est abonnée aux artistes."
        )
        return 1
    print(f"OK : {total} abonnements lisibles avec la clé API.")
    print("Étape suivante : « uv run newrel triage youtube » pour les trier.")
    return github.save_settings(
        secrets={"YOUTUBE_API_KEY": api_key},
        variables={"YOUTUBE_CHANNEL_ID": channel.id},
        use_gh=use_gh,
        repo=repo,
        env_file=env_file,
    )
