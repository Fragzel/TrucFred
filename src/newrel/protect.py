"""Page protégée par mot de passe : les données publiées sont chiffrées.

Le dépôt est public : la page, la branche data et les artefacts des runs sont lisibles par tous.
- releases.json est chiffré en AES-256-GCM avec une clé dérivée du mot de passe de la page
  (SITE_PASSWORD, PBKDF2-SHA256) ; la page le déchiffre dans le navigateur (site/vault.js).
- state.json est chiffré avec une clé aléatoire (STATE_KEY), indépendante du mot de passe :
  changer ce dernier ne fait pas perdre l'état.

Sans ces secrets, les fichiers restent en clair (tests, runs locaux sur les données d'exemple).
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import secrets
import string
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from newrel import github

FORMAT = "newrel-aes-gcm/1"
ITERATIONS = 600_000  # PBKDF2-SHA256 : recommandation OWASP, environ 1 s sur un téléphone
MIN_PASSWORD_LENGTH = 12


class CryptoError(ValueError):
    """Fichier chiffré illisible (clé absente ou erronée, fichier abîmé). Jamais de secret ici."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def normalize(password: str) -> str:
    """Même forme que la page : espaces de bord retirés, Unicode NFC."""
    return unicodedata.normalize("NFC", password.strip())


def derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", normalize(password).encode(), salt, iterations, dklen=32)


def seal(text: str, key: bytes, kdf: dict[str, Any] | None = None) -> str:
    """Enveloppe JSON : un IV neuf à chaque appel, et les paramètres de dérivation éventuels."""
    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(iv, text.encode("utf-8"), None)
    sealed = {"format": FORMAT, "kdf": kdf, "iv": _b64(iv), "ciphertext": _b64(ciphertext)}
    return json.dumps(sealed, indent=2) + "\n"


def envelope(text: str) -> dict[str, Any] | None:
    """L'enveloppe si le texte est chiffré, None s'il est en clair."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("format") == FORMAT else None


def unseal(sealed: dict[str, Any], key: bytes) -> str:
    try:
        plain = AESGCM(key).decrypt(_unb64(sealed["iv"]), _unb64(sealed["ciphertext"]), None)
    except (InvalidTag, KeyError, TypeError, ValueError) as exc:
        raise CryptoError("déchiffrement impossible (clé erronée ou fichier abîmé)") from exc
    return plain.decode("utf-8")


def is_sealed(path: Path) -> bool:
    return path.exists() and envelope(path.read_text(encoding="utf-8")) is not None


def state_key(env: Mapping[str, str]) -> bytes | None:
    """Clé de state.json (STATE_KEY : 32 octets en base64url) ; None si le secret est absent."""
    value = env.get("STATE_KEY", "").strip()
    if not value:
        return None
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        key = b""
    if len(key) != 32:
        raise CryptoError("STATE_KEY invalide (32 octets en base64 attendus)")
    return key


def _site_kdf(previous: Path) -> dict[str, Any]:
    """Paramètres du releases.json précédent : la clé mémorisée par le navigateur (« se souvenir
    de cet appareil ») reste ainsi valable d'un run à l'autre. Sinon, un sel neuf."""
    if previous.exists():
        kdf = (envelope(previous.read_text(encoding="utf-8")) or {}).get("kdf")
        if isinstance(kdf, dict) and kdf.get("iterations") == ITERATIONS and kdf.get("salt"):
            return kdf
    return {"name": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": _b64(os.urandom(16))}


def seal_releases(text: str, password: str, previous: Path) -> str:
    kdf = _site_kdf(previous)
    return seal(text, derive_key(password, _unb64(kdf["salt"]), kdf["iterations"]), kdf)


def generate_password() -> str:
    """Facile à taper sur un téléphone : 5 groupes de 4 lettres, soit environ 94 bits."""
    letters = string.ascii_lowercase
    return "-".join("".join(secrets.choice(letters) for _ in range(4)) for _ in range(5))


def setup(*, use_gh: bool = True, repo: str | None = None, env_file: Path | None = None) -> int:
    """Mise en route ou changement du mot de passe (SITE_PASSWORD), STATE_KEY la première fois."""
    print(
        "Mot de passe de la page. Laisse vide pour en tirer un au hasard (recommandé : sans\n"
        "serveur, rien ne limite les essais de qui a copié les données chiffrées)."
    )
    password = normalize(getpass.getpass("Mot de passe : "))
    if not password:
        password = generate_password()
        print(f"\nMot de passe tiré : {password}\nNote-le dans un gestionnaire de mots de passe.\n")
    elif len(password) < MIN_PASSWORD_LENGTH:
        print(f"Trop court : {MIN_PASSWORD_LENGTH} caractères au moins.")
        return 1
    elif normalize(getpass.getpass("Confirmation : ")) != password:
        print("Les deux saisies diffèrent.")
        return 1

    values = {"SITE_PASSWORD": password}
    # STATE_KEY ne change jamais : une nouvelle clé rendrait illisible l'état de la branche data.
    listed = github.secret_names(repo) if use_gh else set()
    if listed is None:
        print("Impossible de lister les secrets du dépôt : vérifie « gh auth status ».")
        return 1
    if "STATE_KEY" not in listed:
        values["STATE_KEY"] = os.environ.get("STATE_KEY") or secrets.token_urlsafe(32)
    elif env_file and not os.environ.get("STATE_KEY"):
        print(
            "STATE_KEY existe déjà dans le dépôt, mais pas dans .env.local : GitHub ne permet pas\n"
            "de la relire, les runs locaux ne pourront donc pas lire l'état de la branche data."
        )
    status = github.save_settings(
        secrets=values, variables={}, use_gh=use_gh, repo=repo, env_file=env_file
    )
    if status == 0:
        # Un run hors ligne ne réécrit pas la branche data : il faut un run complet.
        print("Tout sera chiffré au prochain run complet (gh workflow run update.yml).")
    return status
