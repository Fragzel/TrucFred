"""Styles musicaux : des genres donnés par les plateformes à une quinzaine de styles lisibles.

- Les genres arrivent en vrac : genres d'artiste Spotify (« rap francais », « frenchcore »),
  genre et tags d'un son SoundCloud (« Drum & Bass »), sujets et tags d'une vidéo YouTube
  (« Electronic music », « acid techno »).
- Chaque genre donne au plus un style, par la première règle qui le reconnaît : les plus
  précises d'abord, pour que « hardcore punk » soit du rock et « hardcore hip hop » du rap.
- L'électro, majoritaire, est découpée en sous-styles. « Électro » (electro) ne reste que
  lorsqu'aucun sous-style n'est reconnu.
- Les tags (SoundCloud, YouTube) citent souvent d'autres genres pour être trouvés : seuls ceux
  de la famille du genre déclaré, ou des sujets de la vidéo, sont gardés.
- Une sortie reçoit un ou deux styles : ceux de ses propres genres d'abord, puis ceux de ses
  artistes, puis ceux de l'ensemble des sorties de ses artistes.
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import cache
from typing import Literal

Style = Literal[
    "hardcore",
    "techno",
    "dnb",
    "bass",
    "house",
    "trance",
    "hardstyle",
    "electro",
    "rap",
    "rnb",
    "pop",
    "rock",
    "reggae",
    "jazz",
    "world",
    "folk",
    "classical",
]
ELECTRO: frozenset[str] = frozenset(
    {"hardcore", "techno", "dnb", "bass", "house", "trance", "hardstyle", "electro"}
)
MAX_STYLES = 2
SECOND_FROM = 0.5
"""Un deuxième style n'est retenu que s'il pèse au moins la moitié du premier."""
MAX_GENRES = 4
"""Genres affichés au survol du style, et cherchables."""
LEVEL_WEIGHTS = (1.0, 0.6, 0.25)
"""Poids des genres de la sortie, de ses artistes, puis de toutes les sorties de ses artistes."""
MAX_WORDS = 4
"""Au-delà, un tag est une phrase (« dub silence nouvel album ») plutôt qu'un genre."""


def _rule(style: Style, *words: str) -> tuple[Style, re.Pattern[str]]:
    return style, re.compile(rf"\b({'|'.join(words)})\b")


# Ordre significatif : la première règle qui reconnaît un genre l'emporte.
RULES: tuple[tuple[Style, re.Pattern[str]], ...] = (
    _rule("rock", r"post hardcore", r"hardcore punk", r"melodic hardcore", r"metalcore"),
    _rule("rock", r"rock", r"metal", r"punk", r"grunge", r"djent", r"shoegaze", r"emo"),
    _rule("rock", r"screamo", r"deathcore", r"grindcore", r"rapcore"),
    _rule("world", r"baile funk", r"funk carioca", r"brazilian funk", r"funk brasileiro"),
    _rule("world", r"funk mandelao", r"latin\w*", r"reggaeton", r"cumbia", r"salsa", r"bachata"),
    _rule("world", r"dembow", r"afrobeats?", r"amapiano", r"zouk", r"kompa", r"kizomba"),
    _rule("world", r"flamenco", r"world", r"music of asia", r"balkan", r"bhangra", r"bossa nova"),
    _rule("bass", r"trap edm", r"edm trap", r"festival trap", r"hybrid trap"),
    _rule("rap", r"hip ?hop", r"rap", r"rapper", r"trap", r"drill", r"grime", r"boom ?bap"),
    _rule("rap", r"phonk", r"type beat", r"instru", r"horrorcore", r"plugg", r"freestyle"),
    _rule("rap", r"g funk"),
    _rule("hardstyle", r"hardstyle", r"rawstyle", r"hard dance", r"jumpstyle", r"euphoric hard"),
    _rule("dnb", r"drum and bass", r"drum ?n ?bass", r"drumandbass", r"dnb", r"d and b"),
    _rule("dnb", r"jungle", r"neurofunk", r"jump ?up", r"liquid funk", r"darkstep", r"techstep"),
    _rule("dnb", r"halftime", r"crossbreed", r"skank and bass", r"skankandbass"),
    _rule("hardcore", r"hardcore", r"gabber", r"gabba", r"frenchcore", r"speedcore"),
    _rule("hardcore", r"terrorcore", r"uptempo", r"splittercore", r"extratone", r"breakcore"),
    _rule("jazz", r"jazz"),
    _rule("house", r"house", r"disco", r"french touch", r"electro swing"),
    _rule("techno", r"techno", r"tekno", r"tekkno", r"hardtek", r"hard tek", r"teknival"),
    _rule("techno", r"free ?party", r"schranz", r"acid", r"minimal", r"tribecore"),
    _rule("trance", r"psytrance", r"psy", r"goa", r"full on", r"hi tech", r"dark ?psy"),
    _rule("trance", r"trance"),
    _rule("bass", r"dubstep", r"riddim", r"brostep", r"bass ?music", r"midtempo", r"future bass"),
    _rule("bass", r"uk garage", r"ukg", r"garage", r"2 ?step", r"breakbeat", r"breaks"),
    _rule("bass", r"big beat", r"glitch hop", r"neurohop", r"jersey club"),
    _rule("reggae", r"reggae", r"dub", r"dancehall", r"ska", r"rocksteady", r"ragga\w*"),
    _rule("reggae", r"steppas?", r"steppers?"),
    _rule("rnb", r"new jack swing", r"r and b", r"rnb", r"rhythm and blues", r"soul", r"gospel"),
    _rule("rnb", r"funk", r"motown"),
    _rule("jazz", r"blues", r"swing", r"bebop", r"big band"),
    _rule("pop", r"pop", r"synthpop", r"electropop", r"dreampop", r"hyperpop", r"britpop"),
    _rule("pop", r"europop", r"[kjc]pop", r"chanson", r"variete\w*", r"cabaret"),
    _rule("folk", r"folk", r"country", r"bluegrass", r"americana", r"acoustic", r"celtic"),
    _rule("folk", r"singer songwriter", r"irish"),
    _rule("classical", r"classical", r"classique", r"orchestral?", r"soundtrack", r"score"),
    _rule("classical", r"cinematic", r"opera", r"piano", r"neo ?classical", r"bande originale"),
    _rule("classical", r"ost", r"baroque", r"symphon\w*"),
    _rule("electro", r"electronic\w*", r"electro", r"edm", r"idm", r"ambient", r"downtempo"),
    _rule("electro", r"chill\w*", r"lo ?fi", r"synthwave", r"darksynth", r"retrowave"),
    _rule("electro", r"trip hop", r"dance", r"club", r"rave", r"experimental", r"glitch"),
    _rule("electro", r"industrial", r"ebm", r"vaporwave"),
)


def normalize(label: str) -> str:
    """« Drum & Bass », « drum'n'bass » et « Drum-n-Bass » → « drum and bass »."""
    text = unicodedata.normalize("NFKD", label)
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    text = re.sub(r"[_/\-.#,;:()\"]+", " ", text)
    text = re.sub(r"\s*[&+]\s*|\s*'n'\s*|\s+'?n'?\s+", " and ", f" {text} ")
    return re.sub(r"\s+", " ", text).strip()


@cache
def style_of(label: str) -> Style | None:
    """Style d'un genre de plateforme, ou None s'il n'en dit rien (« Music », « indie »…)."""
    text = normalize(label)
    if not text or len([word for word in text.split() if word != "and"]) > MAX_WORDS:
        return None
    return next((style for style, pattern in RULES if pattern.search(text)), None)


def family(style: str) -> str:
    """Les sous-styles de l'électro forment une seule famille."""
    return "electro" if style in ELECTRO else style


def split_tags(text: str | None) -> list[str]:
    """Tags séparés par des espaces, entre guillemets s'ils en contiennent (SoundCloud, mots-clés
    des chaînes YouTube) : « techno "acid techno" rave »."""
    try:
        return shlex.split(text or "")
    except ValueError:  # guillemet orphelin
        return (text or "").replace('"', " ").split()


def useful(
    labels: Iterable[str | None], *, within: Iterable[str | None] = (), limit: int = 8
) -> list[str]:
    """Genres qui désignent un style, sans doublon, dans l'ordre reçu.

    within : genres de référence (genre déclaré d'un son, sujets d'une vidéo) ; seuls les
    genres de leurs familles sont gardés. Sans référence reconnue, tout est gardé.
    """
    families = {family(style) for label in within if label and (style := style_of(label))}
    kept: dict[str, str] = {}
    for label in labels:
        label = (label or "").strip()
        style = style_of(label)
        if style is None or (families and family(style) not in families):
            continue
        kept.setdefault(normalize(label), label)
        if len(kept) >= limit:
            break
    return list(kept.values())


def _refine(scores: Counter[str]) -> Counter[str]:
    """« Électro » sans précision renforce le sous-style électro le plus présent, s'il y en a un
    (« Electronic music » et « gabber » → hardcore)."""
    precise = [style for style in ELECTRO - {"electro"} if scores[style]]
    if scores["electro"] and precise:
        scores[max(precise, key=lambda style: (scores[style], style))] += scores.pop("electro")
    return +scores


def _shares(labels: Iterable[str]) -> Counter[str]:
    """Part de chaque style dans une liste de genres (somme 1)."""
    counts = _refine(Counter(style for label in labels if (style := style_of(label))))
    total = sum(counts.values())
    return Counter({style: count / total for style, count in counts.items()})


def pick(levels: Sequence[Iterable[str]]) -> tuple[list[str], list[str]]:
    """Styles d'une sortie et genres qui les justifient, à partir de genres par niveau :
    ceux de la sortie, de ses artistes, puis de toutes les sorties de ses artistes."""
    labels = [[label.strip() for label in level] for level in levels]
    total: Counter[str] = Counter()
    for weight, level in zip(LEVEL_WEIGHTS, labels, strict=False):
        for style, share in _shares(level).items():
            total[style] += weight * share
    total = _refine(total)
    if not total:
        return [], []
    # À égalité, l'ordre des genres reçus départage (sujets YouTube d'abord, par exemple).
    seen = [style for level in labels for label in level if (style := style_of(label))]
    ranked = sorted(total, key=lambda style: (-total[style], seen.index(style)))
    best = total[ranked[0]]
    styles = [style for style in ranked[:MAX_STYLES] if total[style] >= best * SECOND_FROM]
    genres: dict[str, str] = {}
    for label in (label for level in labels for label in level):
        if style_of(label) in styles:
            genres.setdefault(normalize(label), label)
    return styles, list(genres.values())[:MAX_GENRES]
