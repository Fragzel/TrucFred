from datetime import date
from pathlib import Path

import pytest

from newrel import dates
from newrel.config import Aliases, ConfigError, load_aliases, load_config, load_env_file
from newrel.models import ReleasesFile, releases_schema

ROOT = Path(__file__).resolve().parents[1]


def test_config_du_depot_valide() -> None:
    config = load_config(ROOT / "config.toml")
    assert (config.window_days, config.spotify.market, config.spotify.groups) == (
        90,
        "FR",
        ("album", "single"),
    )


@pytest.mark.parametrize(
    "content",
    [
        "[general]\nwindow_dayz = 3\n",
        "[spotify]\ngroups = ['albums']\n",
        "[youtube]\nx = 1\n",
        "[general]\ntimezone = 'Mars/Olympus'\n",
        "[general\n",
    ],
)
def test_config_invalide_refusee(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_config_soundcloud_et_aliases_du_depot() -> None:
    config = load_config(ROOT / "config.toml")
    assert config.soundcloud.exclude == ()
    assert load_aliases(ROOT / "aliases.toml") == Aliases()


def test_aliases(tmp_path: Path) -> None:
    path = tmp_path / "aliases.toml"
    path.write_text(
        '[[same]]\nkeys = ["spotify:artist:A", "soundcloud:users:1"]\n'
        '[[never]]\nkeys = ["spotify:artist:B", "soundcloud:users:2"]\n',
        encoding="utf-8",
    )
    aliases = load_aliases(path)
    assert aliases.same == (frozenset({"spotify:artist:A", "soundcloud:users:1"}),)
    assert aliases.never == (frozenset({"spotify:artist:B", "soundcloud:users:2"}),)
    path.write_text('[[same]]\nkeys = ["spotify:artist:A"]\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_aliases(path)
    path.write_text("[autre]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_aliases(path)


def test_env_local_n_ecrase_pas_l_environnement(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text("# commentaire\nA=fichier\nB = valeur=avec=egal\n", encoding="utf-8")
    environ = {"A": "environnement"}
    load_env_file(path, environ)
    assert environ == {"A": "environnement", "B": "valeur=avec=egal"}


def test_schema_versionne_a_jour() -> None:
    committed = (ROOT / "schema" / "releases.schema.json").read_text(encoding="utf-8")
    assert committed == releases_schema(), (
        "lance « uv run newrel schema » puis versionne le fichier"
    )


def test_donnees_d_exemple_conformes_au_contrat() -> None:
    sample = ReleasesFile.model_validate_json(
        (ROOT / "site" / "sample.json").read_text(encoding="utf-8")
    )
    assert sample.releases


@pytest.mark.parametrize(
    ("value", "precision", "expected"),
    [
        ("2026-10-17", "day", ("2026-10-17", "day")),
        ("2026-10", "day", ("2026-10", "month")),
        ("2026", "year", ("2026", "year")),
        ("0000", "year", None),
        ("2026-13", "month", None),
        ("", "day", None),
    ],
)
def test_dates_partielles(value: str, precision: str, expected) -> None:
    assert dates.normalize(value, precision) == expected


def test_date_de_tri() -> None:
    seen = date(2026, 10, 23)
    assert dates.sort_date("2026-10-17", "day", seen, False) == date(2026, 10, 17)
    assert dates.sort_date("2026", "year", seen, False) == seen
    assert dates.sort_date("2026", "year", seen, True) == date(2026, 1, 1)
    assert dates.sort_date("2026-09", "month", seen, False) == date(2026, 9, 30)
