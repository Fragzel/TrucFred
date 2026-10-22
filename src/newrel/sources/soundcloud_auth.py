"""Mise en route SoundCloud (une fois) : vérifie l'accès en Client Credentials et enregistre tout.

Aucune autorisation utilisateur : tes comptes suivis sont publics. La commande vérifie justement
que l'API accepte de les lire avec un simple jeton d'application, puis enregistre les secrets et
ton URN dans le dépôt.
"""

from __future__ import annotations

from pathlib import Path

from newrel import github
from newrel.config import ask_env
from newrel.http import HttpClient, HttpError
from newrel.sources.soundcloud import SoundCloudApi, _elements


def setup(
    *,
    profile: str | None,
    use_gh: bool = True,
    repo: str | None = None,
    env_file: Path | None = None,
) -> int:
    client_id = ask_env("SOUNDCLOUD_CLIENT_ID")
    client_secret = ask_env("SOUNDCLOUD_CLIENT_SECRET", hidden=True)
    profile = profile or ask_env(
        "SOUNDCLOUD_PROFILE_URL", prompt="Adresse de ton profil (https://soundcloud.com/…)"
    )
    with HttpClient(requests_per_second=2) as client:
        api = SoundCloudApi(client, client_id, client_secret)
        try:
            api.token()
            user = api.resolve_user(profile)
        except HttpError as exc:
            print(f"Échec : {exc}. Vérifie le Client ID, le Client Secret et l'adresse du profil.")
            return 1
        urn, name = user.get("urn"), user.get("username")
        print(
            f"Profil trouvé : {name} ({urn}), {user.get('followings_count', '?')} comptes suivis."
        )
        try:
            page = api.get(f"/users/{urn}/followings", {"limit": 5, "linked_partitioning": "true"})
            sample = _elements(page)
            print("OK : les comptes suivis sont lisibles avec un jeton d'application.")
            if sample:
                api.get(f"/users/{sample[0]['urn']}/tracks", {"limit": 1})
                print(f"OK : les sons sont lisibles (essai sur « {sample[0].get('username')} »).")
        except HttpError as exc:
            print(
                f"Échec : {exc}.\nL'API refuse ces lectures avec un jeton d'application :"
                " il faudra passer par une autorisation utilisateur (OAuth). Signale-le à Claude."
            )
            return 1
    return github.save_settings(
        secrets={"SOUNDCLOUD_CLIENT_ID": client_id, "SOUNDCLOUD_CLIENT_SECRET": client_secret},
        variables={"SOUNDCLOUD_USER_URN": urn},
        use_gh=use_gh,
        repo=repo,
        env_file=env_file,
    )
