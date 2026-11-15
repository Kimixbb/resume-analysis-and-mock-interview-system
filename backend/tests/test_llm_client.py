"""LLM 客户端 URL 拼接的回归测试。"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core import llm


class DemoResult(BaseModel):
    x: int


class FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/chat/completions"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/chat/completions"),
        (
            "https://api.deepseek.com/v1/",
            "https://api.deepseek.com/v1/chat/completions",
        ),
    ],
)
def test_model_json_builds_single_slash_url(monkeypatch, base_url, expected_url):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return FakeResponse('{"x": 1}')

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(
        llm,
        "settings",
        SimpleNamespace(
            openai_base_url=base_url,
            openai_api_key="test-key",
            openai_model="test-model",
            llm_timeout=30,
        ),
    )

    result = llm.model_json("system", "user", DemoResult)

    assert result.x == 1
    assert captured["url"] == expected_url
