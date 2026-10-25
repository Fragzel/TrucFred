"""Tri des abonnements YouTube en local : « uv run newrel triage youtube [--all] ».

La commande classe chaque abonnement comme le ferait le workflow, puis demande ton avis sur les
chaînes douteuses (toutes avec --all). Les réponses vont dans youtube.toml, qu'il reste à
commiter. Seules y sont écrites les réponses qui comptent : une chaîne douteuse tranchée, ou un
classement automatique corrigé. Une chaîne non musicale écartée d'office n'apparaît nulle part.
"""

from __future__ import annotations

import re
import subprocess
import webbrowser
from collections.abc import Callable, Mapping
from pathlib import Path

from newrel.config import Config, load_youtube_triage
from newrel.http import HttpClient, HttpError
from newrel.models import SourceState, State
from newrel.sources import youtube
from newrel.sources.youtube import Channel, Sorting, Verdict, YouTubeApi, topics_label

HEADER = """\
# Tri des abonnements YouTube, tenu à jour par « uv run newrel triage youtube ».
# Tu peux aussi le modifier à la main. Une chaîne absente d'ici est triée automatiquement à
# chaque run (voir le README). Chaque entrée est l'identifiant de la chaîne (UC…) ou son
# handle (@…) ; le commentaire rappelle son nom.
#
# Ce fichier est public, comme le reste du dépôt.
"""
SECTIONS = {
    "artists": "Chaînes à suivre (artistes, labels…), même si le tri automatique hésite.",
    "ignore": "Chaînes à ne jamais suivre, même si le tri automatique les retient.",
}
_LINE = re.compile(r'^\s*"([^"]+)"\s*,?\s*(?:#\s*(.*?))?\s*$')
ANSWERS = {"o": True, "n": False, "p": None}


class TriageFile:
    """youtube.toml : deux listes, avec le nom de chaque chaîne en commentaire."""

    def __init__(self, path: Path) -> None:
        self.path = path
        lists = load_youtube_triage(path)
        comments: dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if (match := _LINE.match(line)) and match.group(2):
                    comments[match.group(1)] = match.group(2)
        self.entries: dict[str, dict[str, str]] = {
            key: {value: comments.get(value, "") for value in lists[key]} for key in SECTIONS
        }

    def decide(self, channel: Channel, follow: bool) -> None:
        names = {channel.id.lower(), channel.handle.lstrip("@")} - {""}
        for entries in self.entries.values():
            for value in [v for v in entries if v.lower().lstrip("@") in names]:
                del entries[value]
        self.entries["artists" if follow else "ignore"][channel.id] = channel.title

    def render(self) -> str:
        parts = [HEADER]
        for key, description in SECTIONS.items():
            lines = [f"# {description}", f"{key} = ["]
            entries = sorted(self.entries[key].items(), key=lambda e: (e[1] or e[0]).casefold())
            for value, comment in entries:
                safe = re.sub(r"[\x00-\x1f\x7f]+", " ", comment).strip()
                quoted = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'    "{quoted}",' + (f"  # {safe}" if safe else ""))
            parts.append("\n".join([*lines, "]"]) + "\n")
        return "\n".join(parts)

    def save(self) -> None:
        self.path.write_text(self.render(), encoding="utf-8", newline="\n")


def published_state(state_dir: Path) -> State | None:
    """État local (worktree data/), sinon celui de la branche data du dépôt."""
    path = state_dir / "state.json"
    if path.exists():
        return State.model_validate_json(path.read_text(encoding="utf-8"))
    try:
        subprocess.run(
            ["git", "fetch", "--quiet", "origin", "data"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        shown = subprocess.run(
            ["git", "show", "FETCH_HEAD:state.json"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        return State.model_validate_json(shown.stdout)
    except OSError, subprocess.SubprocessError, ValueError:
        return None


def _describe(index: int, total: int, channel: Channel, verdict: Verdict, sorting: Sorting) -> str:
    proposal = {True: "à suivre", False: "à écarter", None: "douteuse"}[verdict.follow]
    lines = [
        f"\n[{index}/{total}] {channel.title} · {channel.url}",
        f"  Proposition : {proposal}, car {verdict.reason}",
    ]
    if channel.topics:
        lines.append(f"  Sujets : {topics_label(channel.topics)}")
    titles = [
        (video.get("snippet") or {}).get("title") or ""
        for video in sorting.samples.get(channel.id, [])[:4]
    ]
    if titles := [title if len(title) <= 70 else f"{title[:69]}…" for title in titles if title]:
        lines.append("  Dernières vidéos : " + " · ".join(f"« {title} »" for title in titles))
    return "\n".join(lines)


def _ask(ask: Callable[[str], str], default: str) -> str:
    labels = {"o": "oui", "n": "non", "p": "plus tard"}
    prompt = (
        "Suivre cette chaîne comme artiste ? [o]ui, [n]on, [p]lus tard, [v]oir, [q]uitter"
        f" (Entrée : {labels[default]}) : "
    )
    while True:
        answer = ask(prompt).strip().lower()[:1] or default
        if answer in (*ANSWERS, "v", "q"):
            return answer
        print("Réponds par o, n, p, v ou q.")


def run(
    *,
    config: Config,
    triage_path: Path,
    state: State | None,
    env: Mapping[str, str],
    review_all: bool = False,
    ask: Callable[[str], str] = input,
    http: HttpClient | None = None,
) -> int:
    missing = [name for name in youtube.REQUIRED_ENV if not env.get(name)]
    if missing:
        print(
            f"Secrets absents : {', '.join(missing)}. Lance d'abord"
            " « uv run newrel auth youtube --write-env » (voir le README)."
        )
        return 2
    sources = state.sources if state else {}
    previous = [artist.key for artist in sources.get(youtube.PLATFORM, SourceState()).followings]
    peers = [
        artist.name
        for name, source in sources.items()
        if name != youtube.PLATFORM
        for artist in source.followings
    ]
    if state is None:
        print("État du workflow introuvable : le tri ne s'appuiera pas sur tes artistes Spotify.")
    client = http or HttpClient(requests_per_second=config.youtube.requests_per_second)
    try:
        api = YouTubeApi(client, env["YOUTUBE_API_KEY"])
        print("Lecture des abonnements et des dernières vidéos des chaînes à examiner…")
        sorting = youtube.sort_subscriptions(
            api,
            config.youtube,
            channel_id=env["YOUTUBE_CHANNEL_ID"],
            previous=previous,
            peer_names=peers,
        )
    except HttpError as exc:
        print(f"Échec : {exc}.")
        return 1
    finally:
        if http is None:
            client.close()
    if sorting.problem:
        print(f"[avertissement] tri incomplet : {sorting.problem}")
    _summary(sorting)

    triage = TriageFile(triage_path)
    queue = [
        channel
        for channel in sorting.channels
        if review_all or sorting.verdicts[channel.id].follow is None
    ]
    changed = 0
    try:
        for index, channel in enumerate(queue, start=1):
            verdict = sorting.verdicts[channel.id]
            print(_describe(index, len(queue), channel, verdict, sorting))
            default = {True: "o", False: "n", None: "p"}[verdict.follow if review_all else None]
            while (answer := _ask(ask, default)) == "v":
                webbrowser.open(channel.url)
            if answer == "q":
                break
            follow = ANSWERS[answer]
            # Confirmer un classement automatique ne s'écrit pas : le run arrive au même résultat.
            if follow is None or follow == verdict.follow:
                continue
            triage.decide(channel, follow)
            triage.save()
            changed += 1
    except EOFError, KeyboardInterrupt:
        print()
    _closing(sorting, triage_path, changed, review_all)
    return 0


def _summary(sorting: Sorting) -> None:
    verdicts = [sorting.verdicts[channel.id] for channel in sorting.channels]
    followed = [v for v in verdicts if v.follow]
    ignored = [v for v in verdicts if v.follow is False]
    doubtful = sum(1 for v in verdicts if v.follow is None)
    manual = sum(1 for v in followed if v.manual), sum(1 for v in ignored if v.manual)
    print(f"\nYouTube : {len(verdicts)} abonnements.")
    print(f"  {len(followed)} chaîne(s) d'artiste suivie(s), dont {manual[0]} par youtube.toml")
    print(f"  {len(ignored)} écartée(s), dont {manual[1]} par youtube.toml")
    print(f"  {doubtful} à trier")


def _closing(sorting: Sorting, triage_path: Path, changed: int, review_all: bool) -> None:
    if not review_all:
        automatic = [
            channel for channel in sorting.followed() if not sorting.verdicts[channel.id].manual
        ]
        label_ids = {
            channel.id
            for channel in automatic
            if sorting.verdicts[channel.id].reason.startswith(youtube.LABEL_REASON)
        }
        artists = [channel.title for channel in automatic if channel.id not in label_ids]
        labels = [
            f"{channel.title} ({channel.handle or channel.id})"
            for channel in automatic
            if channel.id in label_ids
        ]
        for heading, names in (
            ("Artistes suivis d'office", artists),
            ("Labels et chaînes de promo suivis d'office", labels),
        ):
            if names:
                print(f"\n{heading} ({len(names)}) : {', '.join(sorted(names, key=str.casefold))}.")
        if automatic:
            print(
                "Pour en écarter un : ajoute son @handle ou son identifiant dans ignore de"
                f" {triage_path.name}, ou « uv run newrel triage youtube --all »."
            )
    if changed:
        print(
            f"\n{changed} décision(s) enregistrée(s) dans {triage_path}. Pour que le workflow en"
            f' tienne compte :\n  git add {triage_path.name} && git commit -m "Tri YouTube"'
            " && git push"
        )
    else:
        print("\nAucune décision nouvelle.")
