"""M4 逐题问答的单元测试：LLM 点评的输入素材、覆盖写入与错误语义。

LLM 用假实现替换，不联网；数据库用 conftest 的独立测试库。
"""

import json

import pytest

from app.contracts.report_schema import QACommentOutput
from app.core.errors import InvalidInput, LLMOutputInvalid, NotFound
from app.services import qa_service


def _fake_llm(monkeypatch, comment: str = "点评：回答缺具体事实，建议补充可验证的数据。"):
    captured: dict = {}

    def fake(*, system, user, schema, temperature=0.2):
        captured["system"] = system
        captured["user"] = json.loads(user)
        if comment.strip():
            return QACommentOutput(comment=comment)
        # 模拟模型返回全空白：绕过校验构造，让服务层自己判空
        return QACommentOutput.model_construct(comment=comment)

    monkeypatch.setattr(qa_service, "model_json", fake)
    return captured


def test_prompt_contains_question_answer_risk_and_keywords(seeded_report, report_payload, monkeypatch):
    captured = _fake_llm(monkeypatch)

    qa_service.evaluate_answer(seeded_report["report_id"], 0, "大概快了很多")

    user = captured["user"]
    assert user["question"] == report_payload["questions"][0]["text"]
    assert user["answer"] == "大概快了很多"
    # 第 0 题指向第 0 条风险
    assert user["risk"]["type"] == report_payload["risks"][0]["type"]
    assert user["jd_keywords"] == report_payload["req"]["keywords"]
    assert "点评" in captured["system"]


def test_comment_is_persisted_and_overwritten(seeded_report, monkeypatch):
    _fake_llm(monkeypatch, comment="点评：第一次")
    qa_service.evaluate_answer(seeded_report["report_id"], 0, "第一次回答，含数字 123")

    _fake_llm(monkeypatch, comment="点评：第二次，建议补基线")
    qa_service.evaluate_answer(seeded_report["report_id"], 0, "第二次回答，含数字 456")

    from app.services.report_service import get_report_by_id

    report = get_report_by_id(seeded_report["report_id"])
    assert len(report.qa) == 1
    assert report.qa[0].comment == "点评：第二次，建议补基线"
    assert report.qa[0].answer == "第二次回答，含数字 456"


def test_blank_comment_raises_llm_output_invalid(seeded_report, monkeypatch):
    _fake_llm(monkeypatch, comment="   ")

    with pytest.raises(LLMOutputInvalid):
        qa_service.evaluate_answer(seeded_report["report_id"], 0, "有数字 123")


def test_out_of_range_index_raises_invalid_input(seeded_report):
    with pytest.raises(InvalidInput):
        qa_service.evaluate_answer(seeded_report["report_id"], 99, "有数字 123")


def test_missing_report_raises_not_found():
    with pytest.raises(NotFound):
        qa_service.evaluate_answer(99999, 0, "有数字 123")
