"""M3 接口：响应、统一错误格式和 OpenAPI 注册。"""

import asyncio
import json
from pathlib import Path

import httpx

from app.contracts.interrogate import InterrogateResult, Question
from app.core.errors import LLMOutputInvalid, LLMUpstreamError
from app.main import app
from app.services import interrogate_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _payload() -> dict:
    return json.loads((FIXTURES / "parsed.json").read_text(encoding="utf-8"))


def _request(method: str, path: str, payload: dict | None = None) -> httpx.Response:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, json=payload)

    loop = asyncio.SelectorEventLoop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def _fake_result() -> InterrogateResult:
    return InterrogateResult(
        questions=[
            Question(text="第一条追问", risk_index=0),
            Question(text="第二条追问", risk_index=1),
        ],
        weakest_experience_id="intern_1",
    )


def test_interrogate_success(monkeypatch):
    monkeypatch.setattr(
        interrogate_service, "model_json", lambda *a, **k: _fake_result()
    )
    response = _request("POST", "/api/interrogate", _payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["risks"]) == 4
    assert [question["risk_index"] for question in body["questions"]] == [0, 1]
    assert body["weakest_experience_id"] == "intern_1"


def test_missing_raw_text_returns_400():
    response = _request(
        "POST",
        "/api/interrogate",
        {"parsed": {"raw_text": ""}, "req": {}},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_llm_invalid_output_returns_422(monkeypatch):
    def fake(*args, **kwargs):
        raise LLMOutputInvalid("模型输出不符合约定")

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    response = _request("POST", "/api/interrogate", _payload())

    assert response.status_code == 422
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"


def test_llm_upstream_failure_returns_500(monkeypatch):
    def fake(*args, **kwargs):
        raise LLMUpstreamError("模型服务请求失败")

    monkeypatch.setattr(interrogate_service, "model_json", fake)
    response = _request("POST", "/api/interrogate", _payload())

    assert response.status_code == 500
    assert response.json()["code"] == "LLM_UPSTREAM_ERROR"


def test_interrogate_is_documented_in_openapi():
    response = _request("GET", "/openapi.json")
    assert response.status_code == 200
    responses = response.json()["paths"]["/api/interrogate"]["post"]["responses"]
    assert {"200", "400", "422", "500"} <= set(responses)
