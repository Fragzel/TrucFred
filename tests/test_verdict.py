from datetime import timedelta

import pytest

from newrel.models import SourceState, State
from newrel.verdict import Verdict, evaluate
from tests.helpers import CONFIG, NOW


def verdict_for(
    status: str | None = "ok", failures: int = 0, authorized_days_ago: int | None = 10, warnings=()
):
    state = State(
        sources={
            "spotify": SourceState(status=status, message="détail", consecutive_failures=failures)
        }
    )
    env = {}
    if authorized_days_ago is not None:
        env["SPOTIFY_AUTHORIZED_AT"] = (NOW - timedelta(days=authorized_days_ago)).isoformat()
    return evaluate(
        Verdict(),
        state,
        platforms=["spotify"],
        warnings=list(warnings),
        env=env,
        now=NOW,
        config=CONFIG,
    )


@pytest.mark.parametrize(
    ("status", "failures", "level"),
    [
        ("ok", 0, "ok"),
        ("partial", 0, "warning"),
        ("error", 1, "warning"),
        ("error", 2, "error"),
        ("auth_expired", 1, "error"),
    ],
)
def test_statut_de_la_source(status: str, failures: int, level: str) -> None:
    assert verdict_for(status, failures).level == level


@pytest.mark.parametrize(("days", "level"), [(149, "ok"), (150, "warning"), (170, "error")])
def test_age_du_refresh_token(days: int, level: str) -> None:
    assert verdict_for(authorized_days_ago=days).level == level


def test_date_d_autorisation_absente_ou_illisible() -> None:
    assert verdict_for(authorized_days_ago=None).level == "warning"
    state = State(sources={"spotify": SourceState(status="ok")})
    env = {"SPOTIFY_AUTHORIZED_AT": "hier"}
    verdict = evaluate(
        Verdict(), state, platforms=["spotify"], warnings=[], env=env, now=NOW, config=CONFIG
    )
    assert verdict.level == "warning"


def test_avertissements_des_sources_remontes() -> None:
    verdict = verdict_for(warnings=["ordre inattendu"])
    assert verdict.level == "warning"
    assert ("warning", "ordre inattendu") in verdict.messages
