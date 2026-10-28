"""M2：根据 M1 的解析结果评估岗位匹配度。"""

import json
from pathlib import Path

from app.contracts.match import MatchResponse, MatchResult
from app.contracts.parse import JDReq, ResumeParsed
from app.core.llm import model_json

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "match.md"


def match_resume(parsed: ResumeParsed, req: JDReq) -> MatchResponse:
    """调用统一 LLM 客户端；非法输出和网络异常交给全局异常处理器。"""
    user_prompt = json.dumps(
        {"parsed": parsed.model_dump(), "req": req.model_dump()},
        ensure_ascii=False,
    )
    result = model_json(
        system=PROMPT_PATH.read_text(encoding="utf-8"),
        user=user_prompt,
        schema=MatchResult,
    )
    return MatchResponse.model_validate(result.model_dump())
