"""M1 数据契约（Pydantic 模型）的单元测试。

契约 = 各模块之间传数据的「字段说明书」，只测结构：
1. 真实样例（fixtures/parsed.json，A 的真实输出）必须能通过校验；
2. LLM 少给了字段时用默认值兜底，不至于一崩到底；
3. LLM 多给了字段直接忽略；
4. 接口入参/出参模型字段齐全。
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.parse import (
    JDReq,
    ParseRequest,
    ParseResponse,
    ParseResult,
    ResumeParsed,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture() -> dict:
    """读 M1 的真实输出样例（由本模块负责人 A 维护）。"""
    return json.loads((FIXTURES_DIR / "parsed.json").read_text(encoding="utf-8"))


def test_fixture_validates_against_parse_result():
    """真实样例必须能原样通过 ParseResult 校验，契约和样例不能打架。"""
    result = ParseResult.model_validate(_fixture())
    assert result.parsed.raw_text.startswith("张三")
    assert [s for s in result.parsed.skills] == ["Python", "FastAPI", "MySQL", "Redis"]
    assert result.parsed.experiences[0].id == "proj_1"
    assert result.parsed.experiences[0].kind == "project"
    assert result.parsed.education[0].school == "XX大学"
    assert result.req.hard_skills == ["Python", "MySQL", "Redis", "高并发"]
    assert result.req.min_years == 3


def test_missing_fields_get_defaults():
    """LLM 少给字段时用默认值，字段全空也能过校验（宽松兜底）。"""
    result = ParseResult.model_validate(
        {
            "parsed": {
                "raw_text": "随便一段原文",
                "skills": ["Python"],
            },
            "req": {},
        }
    )
    assert isinstance(result.parsed, ResumeParsed)
    assert result.parsed.experiences == []  # 没给就默认空列表
    assert result.parsed.metrics == []
    assert isinstance(result.req, JDReq)
    assert result.req.min_years == 0  # 没写最低年限就默认 0
    assert result.req.hard_skills == []


def test_experience_defaults():
    """单条经历里 id/时间等字段都有默认值，不会因为漏一个字段整体报废。"""
    exp = {"kind": "project", "title": "某项目", "raw": "原文"}
    from app.contracts.parse import Experience

    e = Experience.model_validate(exp)
    assert e.id == ""
    assert e.start == ""
    assert e.bullets == []


def test_extra_fields_are_ignored():
    """LLM 多说的字段直接忽略，不让整次解析报错。"""
    result = ParseResult.model_validate(
        {
            "parsed": {"raw_text": "abc", "something_new": 1},
            "req": {"hard_skills": [], "note": "多余的话"},
        }
    )
    assert result.parsed.raw_text == "abc"
    assert not hasattr(result.req, "note")


def test_parse_result_requires_both_parts():
    """parsed 和 req 是必填的：缺任何一个就是契约不合格（上层转 422）。"""
    with pytest.raises(ValidationError):
        ParseResult.model_validate({"parsed": {"raw_text": "abc"}})  # 缺 req


def test_parse_request_and_response_models():
    """接口的入参/出参模型：字段名与设计文档 5.2 一致。"""
    req = ParseRequest.model_validate({"resume_text": "r", "jd_text": "j"})
    assert req.resume_text == "r"
    assert req.jd_text == "j"
    with pytest.raises(ValidationError):
        ParseRequest.model_validate({"resume_text": "r"})  # 缺 jd_text

    parsed = ResumeParsed.model_validate({"raw_text": "r"})
    resp = ParseResponse.model_validate(
        {"parsed": parsed.model_dump(), "req": {"hard_skills": []}}
    )
    assert resp.parsed.raw_text == "r"
    assert resp.req.hard_skills == []
