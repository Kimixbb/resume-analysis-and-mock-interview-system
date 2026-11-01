"""M3 服务：规则结果、LLM 出题、追问校验和最差经历兜底。"""

import json
from pathlib import Path

import pytest

from app.contracts.interrogate import InterrogateResult, Question
from app.contracts.parse import JDReq, ParseResponse, ResumeParsed
from app.core.errors import LLMOutputInvalid, LLMUpstreamError
from app.services import interrogate_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _inputs() -> ParseResponse:
    return ParseResponse.model_validate_json(
        (FIXTURES / "parsed.json").read_text(encoding="utf-8")
    )


def _fake_result() -> InterrogateResult:
    return InterrogateResult(
        questions=[
            Question(text="第一条追问", risk_index=0),
            Question(text="第二条追问", risk_index=1),
            Question(text="第三条追问", risk_index=2),
        ],
        weakest_experience_id="work_1",
    )


def test_service_builds_questions_and_weakest(monkeypatch):
    calls = {}

    def fake(*, system, user, schema, temperature=0.2):
        calls.update(system=system, user=user, schema=schema)
        return _fake_result()

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    source = _inputs()
    result = interrogate_service.interrogate_resume(source.parsed, source.req)

    assert len(result.risks) == 4
    assert [question.text for question in result.questions] == [
        "第一条追问",
        "第二条追问",
        "第三条追问",
    ]
    assert result.weakest_experience_id == "work_1"
    assert calls["schema"] is InterrogateResult
    assert "面试官" in calls["system"]

    sent = json.loads(calls["user"])
    assert len(sent["risks"]) == 4
    assert sent["risks"][0]["risk_index"] == 0
    assert sent["parsed"]["raw_text"] == source.parsed.raw_text
    assert sent["req"]["hard_skills"] == source.req.hard_skills


def test_invalid_and_duplicate_indexes_are_filtered(monkeypatch):
    def fake(*args, **kwargs):
        return InterrogateResult(
            questions=[
                Question(text="越界", risk_index=99),
                Question(text="保留一", risk_index=1),
                Question(text="重复", risk_index=1),
                Question(text="保留二", risk_index=2),
            ],
            weakest_experience_id="work_1",
        )

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    source = _inputs()
    result = interrogate_service.interrogate_resume(source.parsed, source.req)

    assert [question.text for question in result.questions] == ["保留一", "保留二"]
    assert [question.risk_index for question in result.questions] == [1, 2]


def test_all_invalid_indexes_raise(monkeypatch):
    def fake(*args, **kwargs):
        return InterrogateResult(
            questions=[Question(text="全越界", risk_index=99)],
            weakest_experience_id=None,
        )

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    source = _inputs()
    with pytest.raises(LLMOutputInvalid):
        interrogate_service.interrogate_resume(source.parsed, source.req)


def test_invalid_weakest_falls_back_to_rule_choice(monkeypatch):
    def fake(*args, **kwargs):
        return InterrogateResult(
            questions=[Question(text="追问", risk_index=0)],
            weakest_experience_id="not_exists",
        )

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    source = _inputs()
    result = interrogate_service.interrogate_resume(source.parsed, source.req)

    assert result.weakest_experience_id == "proj_1"


def test_no_risks_skips_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("没有风险时不应调用 LLM")

    monkeypatch.setattr(interrogate_service, "model_json", boom)
    parsed = ResumeParsed(
        raw_text="2023.01-2023.12 某项目\nQPS 从 100 提升到 200。"
    )
    result = interrogate_service.interrogate_resume(parsed, JDReq())

    assert result.risks == []
    assert result.questions == []
    assert result.weakest_experience_id is None


@pytest.mark.parametrize("error", [LLMOutputInvalid, LLMUpstreamError])
def test_preserves_llm_errors(monkeypatch, error):
    def fake(*args, **kwargs):
        raise error("模型调用失败")

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    source = _inputs()
    with pytest.raises(error):
        interrogate_service.interrogate_resume(source.parsed, source.req)
