"""M2 契约边界：样例、整数总分、三条差距和可选分项。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.match import MatchRequest, MatchResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _match_payload() -> dict:
    return json.loads((FIXTURES / "match.json").read_text(encoding="utf-8"))


def test_match_fixture_satisfies_contract():
    result = MatchResponse.model_validate(_match_payload())
    assert result.score == 58
    assert len(result.gaps) == 3


@pytest.mark.parametrize("score", [-1, 101, 58.5, True])
def test_score_must_be_integer_in_range(score):
    payload = _match_payload()
    payload["score"] = score
    with pytest.raises(ValidationError):
        MatchResponse.model_validate(payload)


@pytest.mark.parametrize("count", [0, 2, 4])
def test_gaps_must_have_exactly_three_items(count):
    payload = _match_payload()
    payload["gaps"] = payload["gaps"][:1] * count
    with pytest.raises(ValidationError):
        MatchResponse.model_validate(payload)


def test_dimensions_have_no_undocumented_caps_or_sum_rule():
    payload = _match_payload()
    assert payload["dimensions"]["domain"] == 12
    assert MatchResponse.model_validate(payload).dimensions.domain == 12
    payload["score"] = 59
    assert MatchResponse.model_validate(payload).score == 59


def test_dimensions_can_be_omitted():
    payload = _match_payload()
    payload.pop("dimensions")
    assert MatchResponse.model_validate(payload).dimensions is None


def test_match_request_reuses_m1_contract_and_requires_content():
    parsed = json.loads((FIXTURES / "parsed.json").read_text(encoding="utf-8"))
    assert MatchRequest.model_validate(parsed).req.min_years == 3
    with pytest.raises(ValidationError):
        MatchRequest.model_validate({"parsed": parsed["parsed"]})
    with pytest.raises(ValidationError):
        MatchRequest.model_validate({"parsed": {}, "req": {}})
