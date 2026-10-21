import httpx
import pytest
import respx

from newrel.http import HttpClient, HttpError, RateLimited, mask

URL = "https://api.example.test/ressource"


def client_with_sleeps(**options: object) -> tuple[HttpClient, list[float]]:
    sleeps: list[float] = []
    return HttpClient(requests_per_second=0, sleep=sleeps.append, **options), sleeps  # type: ignore[arg-type]


@respx.mock
def test_retry_after_est_respecte() -> None:
    respx.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200)]
    )
    client, sleeps = client_with_sleeps()
    assert client.request("GET", URL).status_code == 200
    assert sleeps == [3.0]
    assert client.calls == 2


@respx.mock
def test_attente_trop_longue_arrete_le_run() -> None:
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "900"}))
    client, sleeps = client_with_sleeps()
    with pytest.raises(RateLimited, match="900"):
        client.request("GET", URL)
    assert sleeps == []


@respx.mock
def test_quota_epuise_sans_nouvel_essai() -> None:
    body = {"error": {"status": 429, "message": "Too many requests", "reason": "QUOTA_EXCEEDED"}}
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "1"}, json=body))
    client, sleeps = client_with_sleeps()
    with pytest.raises(RateLimited, match="QUOTA_EXCEEDED"):
        client.request("GET", URL)
    assert sleeps == []


@respx.mock
def test_erreurs_serveur_reessayees_avec_attente_croissante() -> None:
    respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200)])
    client, sleeps = client_with_sleeps()
    assert client.request("GET", URL).status_code == 200
    assert sleeps == [1, 2]


@respx.mock
def test_erreur_serveur_persistante_renvoyee_a_l_appelant() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    client, _ = client_with_sleeps(retries=2)
    assert client.request("GET", URL).status_code == 500


@respx.mock
def test_erreur_reseau_devient_http_error_sans_secret() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("refusé"))
    client, sleeps = client_with_sleeps(retries=2)
    with pytest.raises(HttpError, match="GET /ressource : ConnectError"):
        client.request("GET", f"{URL}?token=secret")
    assert sleeps == [1, 2]


def test_debit_limite_espace_les_requetes() -> None:
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    client = HttpClient(requests_per_second=2, sleep=sleep, clock=lambda: clock[0])
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200))
        for _ in range(3):
            client.request("GET", URL)
    assert sleeps == [0.5, 0.5]


def test_masquage_uniquement_dans_github_actions(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    mask("valeur-secrete")
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    mask("valeur-secrete")
    mask(None)
    assert capsys.readouterr().out == "::add-mask::valeur-secrete\n"
