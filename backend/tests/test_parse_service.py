"""M1 解析服务（parse_resume）的单元测试。

用 monkeypatch 把真正的 LLM 调用（model_json）换成假实现，
所以测试不需要网络、不需要 API Key，也不测 LLM 本身，只测我们自己的逻辑：
输入校验 → 拼 Prompt → 调 LLM → 补 raw_text/经历 id → 返回。
"""

import pytest

from app.contracts.parse import ParseResult, ParseResponse
from app.core.errors import InvalidInput, LLMOutputInvalid, LLMUpstreamError
from app.services import parse_service
from app.services.parse_service import parse_resume

# 正常输入：简历 strip 后 100 字、JD 50 字（FR-001 的下限）
RESUME_OK = "姓名张三，后端开发工程师，负责接口开发与性能优化。" * 5  # 125 字
JD_OK = "岗位：后端开发工程师，要求熟悉Python与MySQL，参与高并发系统设计。" * 2  # 76 字


def _llm_payload() -> dict:
    """假 LLM 会返回的最小合法 JSON（模拟模型按 prompt 输出的样子）。"""
    return {
        "parsed": {
            "raw_text": "LLM 自己编的原文，后端应该用真实原文覆盖它",
            "skills": ["Python", "MySQL"],
            "experiences": [
                {  # 注意：故意不给 id，测试后端会不会自动补
                    "kind": "project",
                    "title": "校园二手交易平台",
                    "raw": "2024.09-2024.06 校园二手交易平台",
                    "bullets": ["负责后端开发"],
                    "metrics": [],
                },
                {
                    "kind": "intern",
                    "title": "后端开发实习生",
                    "raw": "2023.07-2023.09 XX科技有限公司",
                    "bullets": ["负责接口开发"],
                    "metrics": [],
                },
            ],
            "education": [],
            "metrics": [],
        },
        "req": {
            "hard_skills": ["Python", "MySQL"],
            "responsibilities": ["负责订单服务开发"],
            "keywords": ["高并发"],
            "min_years": 3,
        },
    }


def _fake_llm_ok(monkeypatch, calls: dict):
    """把 model_json 换成「返回合法结果 + 记录入参」的假函数。"""

    def fake(system, user, schema, temperature=0.2):
        calls["system"] = system
        calls["user"] = user
        calls["schema"] = schema
        return ParseResult.model_validate(_llm_payload())

    monkeypatch.setattr(parse_service, "model_json", fake)


def test_parse_resume_happy_path(monkeypatch):
    """正常输入 → 返回 parsed + req，且 raw_text 与请求原文完全一致（FR-002）。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    result = parse_resume(RESUME_OK + "\n", JD_OK)

    assert isinstance(result, ParseResponse)
    # 契约红线：raw_text 等于请求里的 resume_text 原文（连结尾换行都要原样保留）
    assert result.parsed.raw_text == RESUME_OK + "\n"
    # LLM 带回的假原文必须被覆盖掉
    assert "LLM 自己编的原文" not in result.parsed.raw_text
    assert result.req.min_years == 3
    assert result.req.hard_skills == ["Python", "MySQL"]


def test_llm_gets_prompt_with_both_texts(monkeypatch):
    """拼 Prompt：简历和 JD 都要进 user 消息，schema 必须是 ParseResult。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    parse_resume(RESUME_OK, JD_OK)

    assert calls["schema"] is ParseResult
    assert RESUME_OK in calls["user"]
    assert JD_OK in calls["user"]
    assert len(calls["system"]) > 50  # system 是 prompts/parse.md 的内容，不可能为空


def test_llm_omits_raw_text_is_still_ok(monkeypatch):
    """LLM 按 prompt 要求不带回 raw_text 时，解析也要成功。

    （真实联调时发现的问题：prompt 让模型别输出 raw_text，
    但契约里它曾经是必填字段，导致真实调用必然 422。）
    """
    payload = _llm_payload()
    del payload["parsed"]["raw_text"]  # 模拟模型不带回原文

    def fake(system, user, schema, temperature=0.2):
        return ParseResult.model_validate(payload)

    monkeypatch.setattr(parse_service, "model_json", fake)

    result = parse_resume(RESUME_OK, JD_OK)

    # 后端照样用真实原文补上
    assert result.parsed.raw_text == RESUME_OK


def test_missing_experience_ids_are_filled(monkeypatch):
    """LLM 忘了给经历 id 时，后端自动补成唯一的 exp_1、exp_2（M3 要靠 id 找经历）。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    result = parse_resume(RESUME_OK, JD_OK)

    ids = [e.id for e in result.parsed.experiences]
    assert ids == ["exp_1", "exp_2"]


def test_duplicate_experience_ids_are_deduped(monkeypatch):
    """两条经历给了同一个 id：保留第一个，第二个自动改名，保证 id 唯一。"""
    payload = _llm_payload()
    for exp in payload["parsed"]["experiences"]:
        exp["id"] = "same_id"

    def fake(system, user, schema, temperature=0.2):
        return ParseResult.model_validate(payload)

    monkeypatch.setattr(parse_service, "model_json", fake)

    result = parse_resume(RESUME_OK, JD_OK)

    ids = [e.id for e in result.parsed.experiences]
    assert ids[0] == "same_id"  # 第一个保留
    assert ids[1] != "same_id"  # 第二个被改成别的
    assert len(set(ids)) == 2  # 最终全部唯一


def test_empty_resume_is_rejected(monkeypatch):
    """简历为空 → 400（INVALID_INPUT），根本不该去调 LLM。"""
    called = {"n": 0}

    def fake(system, user, schema, temperature=0.2):
        called["n"] += 1
        return ParseResult.model_validate(_llm_payload())

    monkeypatch.setattr(parse_service, "model_json", fake)

    with pytest.raises(InvalidInput):
        parse_resume("", JD_OK)
    with pytest.raises(InvalidInput):
        parse_resume("   \n  ", JD_OK)  # 全是空白也算空
    assert called["n"] == 0  # 校验失败就不该碰 LLM


def test_resume_too_short_is_rejected(monkeypatch):
    """简历 strip 后不足 100 字 → 400，提示里带最低字数（TC-API-01）。"""
    monkeypatch.setattr(parse_service, "model_json", lambda *a, **k: None)

    with pytest.raises(InvalidInput) as err:
        parse_resume("太短的简历", JD_OK)
    assert "100" in err.value.message


def test_resume_exactly_100_chars_passes(monkeypatch):
    """边界：简历正好 100 字应该放行（100–8000 字是闭区间）。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    resume_100 = "字" * 100
    result = parse_resume(resume_100, JD_OK)

    assert result.parsed.raw_text == resume_100


def test_jd_too_short_is_rejected(monkeypatch):
    """JD strip 后不足 50 字 → 400（TC-API-02）。"""
    monkeypatch.setattr(parse_service, "model_json", lambda *a, **k: None)

    with pytest.raises(InvalidInput) as err:
        parse_resume(RESUME_OK, "太短")
    assert "50" in err.value.message


def test_jd_exactly_50_chars_passes(monkeypatch):
    """边界：JD 正好 50 字应该放行。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    jd_50 = "求" * 50
    result = parse_resume(RESUME_OK, jd_50)

    assert result.req.min_years == 3  # 假数据原样带回来了，说明 50 字边界放行


def test_overlong_resume_is_truncated(monkeypatch):
    """简历 9000 字 → 静默截断到 8000 字再解析（TC-API-03），raw_text 也是截断后的。"""
    calls: dict = {}
    _fake_llm_ok(monkeypatch, calls)

    resume_9000 = "简" * 9000
    result = parse_resume(resume_9000, JD_OK)

    assert len(result.parsed.raw_text) == 8000
    assert result.parsed.raw_text == resume_9000[:8000]
    assert resume_9000[:8000] in calls["user"]  # 发给 LLM 的也是截断后的文本


def test_llm_invalid_output_propagates(monkeypatch):
    """LLM 输出不是合法契约 → 抛 LLM_OUTPUT_INVALID（上层转 422），服务不吞异常。"""

    def fake(system, user, schema, temperature=0.2):
        raise LLMOutputInvalid("模型输出不符合约定")

    monkeypatch.setattr(parse_service, "model_json", fake)

    with pytest.raises(LLMOutputInvalid):
        parse_resume(RESUME_OK, JD_OK)


def test_llm_upstream_error_propagates(monkeypatch):
    """LLM 超时/网络异常 → 抛 LLM_UPSTREAM_ERROR（上层转 500）。"""

    def fake(system, user, schema, temperature=0.2):
        raise LLMUpstreamError("模型服务请求失败")

    monkeypatch.setattr(parse_service, "model_json", fake)

    with pytest.raises(LLMUpstreamError):
        parse_resume(RESUME_OK, JD_OK)
