"""可选真实 LLM 集成测试；未配置真实密钥时自动跳过。"""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.contracts.match import MatchResponse
from app.contracts.parse import ParseResponse
from app.services.match_service import match_resume

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PLACEHOLDERS = ("把这里换成", "your-key", "your-model", "test-key")


def _llm_ready() -> bool:
    key = settings.openai_api_key.strip()
    model = settings.openai_model.strip()
    return bool(key and model) and not any(
        placeholder in key or placeholder in model for placeholder in PLACEHOLDERS
    )


pytestmark = pytest.mark.skipif(not _llm_ready(), reason="未配置真实 LLM")


def test_real_llm_match_contract():
    source = ParseResponse.model_validate_json(
        (FIXTURES / "parsed.json").read_text(encoding="utf-8")
    )
    result = match_resume(source.parsed, source.req)
    assert isinstance(result, MatchResponse)
    assert 0 <= result.score <= 100
    assert len(result.gaps) == 3
    print(json.dumps(result.model_dump(exclude_none=True), ensure_ascii=False, indent=2))
