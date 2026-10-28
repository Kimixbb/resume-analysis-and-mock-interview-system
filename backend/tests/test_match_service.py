"""M2 服务：验证发送给 LLM 的内容和异常传递。"""

import json
from pathlib import Path

import pytest

from app.contracts.match import MatchResponse, MatchResult
from app.contracts.parse import ParseResponse
from app.core.errors import LLMOutputInvalid, LLMUpstreamError
from app.services import match_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _inputs():
    return ParseResponse.model_validate_json(
        (FIXTURES / "parsed.json").read_text(encoding="utf-8")
    )


def _result():
    return MatchResult.model_validate_json(
        (FIXTURES / "match.json").read_text(encoding="utf-8")
    )


def test_match_sends_parsed_and_req_and_returns_contract(monkeypatch):
    calls = {}

    def fake(system, user, schema, temperature=0.2):
        calls.update(system=system, user=user, schema=schema)
        return _result()

    monkeypatch.setattr(match_service, "model_json", fake)
    source = _inputs()
    result = match_service.match_resume(source.parsed, source.req)

    assert isinstance(result, MatchResponse)
    assert result.score == 58
    assert len(result.gaps) == 3
    assert calls["schema"] is MatchResult
    assert "hard_skill" in calls["system"]
    sent = json.loads(calls["user"])
    assert sent["parsed"]["raw_text"] == source.parsed.raw_text
    assert sent["req"]["hard_skills"] == source.req.hard_skills


@pytest.mark.parametrize("error", [LLMOutputInvalid, LLMUpstreamError])
def test_match_preserves_llm_errors(monkeypatch, error):
    def fake(*args, **kwargs):
        raise error("模型调用失败")

    monkeypatch.setattr(match_service, "model_json", fake)
    source = _inputs()
    with pytest.raises(error):
        match_service.match_resume(source.parsed, source.req)
