import base64
import json
import re
from pathlib import Path

import pytest

from newrel import pipeline, protect
from newrel.cli import _summary
from tests.helpers import CONFIG, ENV, NOW, SOURCES
from tests.spotify_fake import album

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
FIXTURE = Path(__file__).parent / "fixtures" / "sealed.json"
PASSWORD = "kfwz-pqam-tvhe-ruxo-lbcn"
STATE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
PROTECTED = ENV | {"SITE_PASSWORD": PASSWORD, "STATE_KEY": STATE_KEY}


@pytest.fixture(autouse=True)
def quick_kdf(monkeypatch):
    """600 000 itérations à chaque run ralentiraient les tests sans rien vérifier de plus."""
    monkeypatch.setattr(protect, "ITERATIONS", 1000)


@pytest.fixture
def one_artist(fake_spotify):
    fake_spotify.follow(("A1", "Nora Velasco"))
    fake_spotify.publish("A1", "single", album("s1", "Lumières froides", "2026-10-16"))
    return fake_spotify


def run(tmp_path: Path, env=PROTECTED, **options):
    return pipeline.run(
        config=CONFIG,
        state_dir=tmp_path / "data",
        out_dir=tmp_path / "_site",
        site_dir=SITE_DIR,
        env=env,
        now=NOW,
        sources=SOURCES,
        **options,
    )


def opened(path: Path, password: str = PASSWORD) -> dict:
    sealed = protect.envelope(path.read_text(encoding="utf-8"))
    assert sealed is not None, f"{path.name} est en clair"
    kdf = sealed["kdf"]
    key = protect.derive_key(password, base64.b64decode(kdf["salt"]), kdf["iterations"])
    return json.loads(protect.unseal(sealed, key))


def test_fichier_de_reference_partage_avec_la_page() -> None:
    """Même fichier que tests/js/vault.test.js : Python et WebCrypto restent compatibles."""
    data = opened(FIXTURE, password="  écho-pqam-tvhe ")  # accent décomposé, espaces
    assert data == {"généré": "par Python", "releases": []}


def test_mauvaise_cle_refusee_sans_rien_reveler() -> None:
    sealed = protect.envelope(protect.seal("secret", bytes(32)))
    with pytest.raises(protect.CryptoError) as error:
        protect.unseal(sealed, bytes([1] * 32))
    assert "secret" not in str(error.value)


def test_cle_d_etat() -> None:
    assert protect.state_key({}) is None
    assert protect.state_key({"STATE_KEY": STATE_KEY}) == bytes(range(32))
    with pytest.raises(protect.CryptoError):
        protect.state_key({"STATE_KEY": "trop-courte"})


def test_mot_de_passe_tire_au_hasard() -> None:
    password = protect.generate_password()
    assert re.fullmatch(r"[a-z]{4}(-[a-z]{4}){4}", password)
    assert password != protect.generate_password()


def test_page_etat_et_resume_proteges(tmp_path, one_artist) -> None:
    outcome = run(tmp_path)
    page = opened(tmp_path / "_site" / "releases.json")
    assert [release["title"] for release in page["releases"]] == ["Lumières froides"]
    assert (tmp_path / "data" / "releases.json").read_text(encoding="utf-8") == (
        tmp_path / "_site" / "releases.json"
    ).read_text(encoding="utf-8")
    state_text = (tmp_path / "data" / "state.json").read_text(encoding="utf-8")
    assert "Nora" not in state_text and protect.envelope(state_text)["kdf"] is None
    assert outcome.protected
    assert "Lumières froides" not in _summary(outcome)  # le résumé du run est public


def test_sel_conserve_d_un_run_a_l_autre(tmp_path, one_artist) -> None:
    """Sinon la clé mémorisée par le navigateur ne servirait qu'une journée."""
    run(tmp_path)
    first = protect.envelope((tmp_path / "_site" / "releases.json").read_text(encoding="utf-8"))
    run(tmp_path)
    second = protect.envelope((tmp_path / "_site" / "releases.json").read_text(encoding="utf-8"))
    assert second["kdf"] == first["kdf"]
    assert second["iv"] != first["iv"]


def test_page_protegee_jamais_republiee_en_clair(tmp_path, one_artist) -> None:
    run(tmp_path)
    before = (tmp_path / "data" / "releases.json").read_bytes()
    without_password = {key: value for key, value in PROTECTED.items() if key != "SITE_PASSWORD"}
    with pytest.raises(pipeline.FatalError, match="SITE_PASSWORD"):
        run(tmp_path, env=without_password)
    assert (tmp_path / "data" / "releases.json").read_bytes() == before
    assert protect.is_sealed(tmp_path / "_site" / "releases.json")


def test_etat_chiffre_sans_sa_cle_arrete_tout(tmp_path, one_artist) -> None:
    run(tmp_path)
    with pytest.raises(pipeline.FatalError, match="STATE_KEY"):
        run(tmp_path, env=ENV | {"SITE_PASSWORD": PASSWORD})


def test_etat_en_clair_converti_au_premier_run_protege(tmp_path, one_artist) -> None:
    run(tmp_path, env=ENV)
    assert not protect.is_sealed(tmp_path / "data" / "state.json")
    outcome = run(tmp_path)
    assert protect.is_sealed(tmp_path / "data" / "state.json")
    assert not any("démarrage à zéro" in message for _, message in outcome.verdict.messages)


def test_mot_de_passe_sans_cle_d_etat_signale(tmp_path, one_artist) -> None:
    outcome = run(tmp_path, env=ENV | {"SITE_PASSWORD": PASSWORD})
    assert protect.is_sealed(tmp_path / "_site" / "releases.json")
    assert not protect.is_sealed(tmp_path / "data" / "state.json")
    assert any("STATE_KEY" in message for _, message in outcome.verdict.messages)
