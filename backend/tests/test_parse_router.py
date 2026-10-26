"""POST /api/parse 接口测试（进程内直调 FastAPI 应用，不起真实服务）。

LLM 仍然用假实现替换，这里重点测的是「接口这一层的规矩」：
状态码（200/400/422/500）、响应体 {code, message} 的错误格式（NFR-001）、
以及 parsed.raw_text 与请求原文一致的契约红线。
"""

import asyncio
from pathlib import Path

import httpx

from app.contracts.parse import ParseResult
from app.core.errors import LLMOutputInvalid, LLMUpstreamError
from app.main import app
from app.services import parse_service
from tests.test_parse_service import _llm_payload, JD_OK, RESUME_OK

PARSE_URL = "/api/parse"

# fixtures 里放着组内统一的样例简历和 JD
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _read_fixture(name: str) -> str:
    """读 fixtures 里的文本样例文件。"""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _request(
    method: str,
    url: str,
    json: dict | None = None,
    content: bytes | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """在进程内直接调用 FastAPI 应用，不走真实网络端口。

    为什么不用 TestClient：它在 Windows 上会留后台事件循环线程，退出时偶发崩溃。
    这里每次请求都新建并立刻关掉一个事件循环，测试结果更稳定。
    另外特意用 SelectorEventLoop：Windows + Python 3.10 的 ProactorEventLoop
    在关闭时有崩溃 bug（3.10.3 已修复），而进程内调用不涉及真实网络，
    用哪个事件循环都行，选个不崩的就好。
    """
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # 直接把请求交给 app 处理
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            return await ac.request(
                method, url, json=json, content=content, headers=headers
            )

    loop = asyncio.SelectorEventLoop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()  # 测试结束前一定关掉循环，不留后台线程


def _post_parse(payload: dict) -> httpx.Response:
    """便捷方法：POST /api/parse。"""
    return _request("POST", PARSE_URL, payload)


def _fake_llm_ok(monkeypatch) -> None:
    """把 model_json 换成「总是返回合法结果」的假实现。"""
    monkeypatch.setattr(
        parse_service,
        "model_json",
        lambda system, user, schema, temperature=0.2: ParseResult.model_validate(
            _llm_payload()
        ),
    )


def test_parse_returns_parsed_and_req(monkeypatch):
    """合法输入 → 200，且 parsed.raw_text 等于请求里的 resume_text（FR-002 验收）。"""
    monkeypatch.setattr(
        parse_service,
        "model_json",
        lambda system, user, schema, temperature=0.2: ParseResult.model_validate(
            _llm_payload()
        ),
    )

    resp = _post_parse({"resume_text": RESUME_OK, "jd_text": JD_OK})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"parsed", "req"}
    assert body["parsed"]["raw_text"] == RESUME_OK
    assert body["req"]["hard_skills"] == ["Python", "MySQL"]
    # 经历 id 被后端补齐，M3 拿到的 id 一定非空
    assert body["parsed"]["experiences"][0]["id"] == "exp_1"


def test_parse_missing_field_returns_400():
    """缺字段（比如没传 jd_text）→ 400 + {code, message}。"""
    resp = _post_parse({"resume_text": RESUME_OK})

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "message" in body


def test_parse_short_resume_returns_400(monkeypatch):
    """简历 99 字 → 400，提示「简历字数不足100字」（TC-API-01）。"""
    _fake_llm_ok(monkeypatch)  # 就算 LLM 可用，校验也应该先拦住

    resp = _post_parse({"resume_text": "太短", "jd_text": JD_OK})

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "简历字数不足100字" in body["message"]


def test_parse_short_jd_returns_400(monkeypatch):
    """JD 49 字 → 400，提示「JD字数不足50字」（TC-API-02）。"""
    _fake_llm_ok(monkeypatch)

    resp = _post_parse({"resume_text": RESUME_OK, "jd_text": "太短"})

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "JD字数不足50字" in body["message"]


def test_parse_empty_resume_returns_400(monkeypatch):
    """简历为空字符串 → 400（TC-API-04）。"""
    _fake_llm_ok(monkeypatch)

    resp = _post_parse({"resume_text": "", "jd_text": JD_OK})

    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


def test_parse_overlong_resume_is_truncated(monkeypatch):
    """简历 9000 字 → 200 不报错，raw_text 截断成 8000 字（TC-API-03）。"""
    _fake_llm_ok(monkeypatch)

    resp = _post_parse({"resume_text": "简" * 9000, "jd_text": JD_OK})

    assert resp.status_code == 200
    assert len(resp.json()["parsed"]["raw_text"]) == 8000


def test_parse_llm_bad_output_returns_422(monkeypatch):
    """LLM 输出不是合法 JSON/字段缺失 → 422 + LLM_OUTPUT_INVALID。"""

    def fake(system, user, schema, temperature=0.2):
        raise LLMOutputInvalid("模型输出不符合约定")

    monkeypatch.setattr(parse_service, "model_json", fake)

    resp = _post_parse({"resume_text": RESUME_OK, "jd_text": JD_OK})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "LLM_OUTPUT_INVALID"
    assert "message" in body


def test_parse_llm_timeout_returns_500(monkeypatch):
    """LLM 超时/网络异常 → 500 + LLM_UPSTREAM_ERROR（不是 422，也不是崩溃）。"""

    def fake(system, user, schema, temperature=0.2):
        raise LLMUpstreamError("模型服务请求失败")

    monkeypatch.setattr(parse_service, "model_json", fake)

    resp = _post_parse({"resume_text": RESUME_OK, "jd_text": JD_OK})

    assert resp.status_code == 500
    assert resp.json()["code"] == "LLM_UPSTREAM_ERROR"


def test_parse_route_is_registered_in_openapi():
    """/api/parse 要出现在接口文档（OpenAPI）里，方便联调。"""
    resp = _request("GET", "/openapi.json")

    assert resp.status_code == 200
    assert PARSE_URL in resp.json()["paths"]


def test_parse_error_statuses_are_documented_in_openapi():
    """400/422/500 都要在 /docs 里登记，不让联调的人看到 Undocumented。"""
    declared = set(
        _request("GET", "/openapi.json").json()["paths"][PARSE_URL]["post"]["responses"]
    )
    assert {"200", "400", "422", "500"} <= declared


def test_parse_invalid_json_body_gets_a_clear_400():
    """请求体本身不是合法 JSON → 400，并且提示要能看出「是 JSON 格式错了」。

    场景：在 Swagger 里粘贴简历时，字符串中间带了真实换行——
    JSON 的字符串不允许直接换行（要写成 \n），整个请求体就不合法了。
    """
    bad_body = '{"resume_text": "张三\n求职意向", "jd_text": "岗位JD"}'.encode("utf-8")

    resp = _request(
        "POST",
        PARSE_URL,
        content=bad_body,
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "JSON" in body["message"]  # 提示里要说明白是 JSON 格式的问题


def test_parse_with_properly_escaped_multiline_text_succeeds(monkeypatch):
    """同样的多行文本，只要换行写成 \\n（合法 JSON），就应该正常解析。

    httpx 的 json= 参数会自动把换行转义成 \n，这里模拟的是「正确的粘贴方式」。
    """
    _fake_llm_ok(monkeypatch)

    payload = {
        "resume_text": _read_fixture("resume_bad.txt"),
        "jd_text": _read_fixture("jd_backend.txt"),
    }
    resp = _post_parse(payload)

    assert resp.status_code == 200
    assert resp.json()["parsed"]["raw_text"] == _read_fixture("resume_bad.txt")
