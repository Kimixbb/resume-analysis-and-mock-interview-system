"""M2 接口的响应、统一错误格式及 OpenAPI 注册。"""

import asyncio
import json
from pathlib import Path

import httpx

from app.contracts.match import MatchResult
from app.core.errors import LLMOutputInvalid, LLMUpstreamError
from app.main import app
from app.services import match_service

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


def test_match_success(monkeypatch):
    fixture = MatchResult.model_validate_json(
        (FIXTURES / "match.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(match_service, "model_json", lambda *a, **k: fixture)
    response = _request("POST", "/api/match", _payload())
    assert response.status_code == 200
    assert response.json()["score"] == 58
    assert len(response.json()["gaps"]) == 3


def test_missing_input_returns_400():
    response = _request("POST", "/api/match", {"parsed": _payload()["parsed"]})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_empty_input_returns_400():
    response = _request("POST", "/api/match", {"parsed": {}, "req": {}})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_llm_invalid_output_returns_422(monkeypatch):
    def fake(*args, **kwargs):
        raise LLMOutputInvalid("模型输出不符合约定")

    monkeypatch.setattr(match_service, "model_json", fake)
    response = _request("POST", "/api/match", _payload())
    assert response.status_code == 422
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"


def test_llm_upstream_failure_returns_500(monkeypatch):
    def fake(*args, **kwargs):
        raise LLMUpstreamError("模型服务请求失败")

    monkeypatch.setattr(match_service, "model_json", fake)
    response = _request("POST", "/api/match", _payload())
    assert response.status_code == 500
    assert response.json()["code"] == "LLM_UPSTREAM_ERROR"


def test_match_is_documented_in_openapi():
    response = _request("GET", "/openapi.json")
    assert response.status_code == 200
    responses = response.json()["paths"]["/api/match"]["post"]["responses"]
    assert {"200", "400", "422", "500"} <= set(responses)
