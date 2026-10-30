"""M3 拷问服务：规则层找风险，LLM 生成追问和最差经历。"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.interrogate import (
    InterrogateResponse,
    InterrogateResult,
    Question,
    RiskItem,
)
from app.contracts.parse import JDReq, ResumeParsed
from app.core.errors import LLMOutputInvalid
from app.core.llm import model_json
from app.services.interrogate_locate import locate_span
from app.services.interrogate_rules import scan_rules

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "interrogate.md"


def _pick_weakest(parsed: ResumeParsed, risks: list[RiskItem]) -> str | None:
    """LLM 没给或给错时，用规则选一段最该重写的经历。"""
    """ 直接用代码算分数 """
    if not parsed.experiences:
        return None

    def score(experience) -> int:
        text = experience.raw or ""
        value = 3 * sum(
            1 for risk in risks if risk.experience_id == experience.id
        )
        if text and not any(char.isdigit() for char in text):
            value += 2
        if len(text) < 80:
            value += 1
        if not experience.metrics:
            value += 1
        return value

    return max(parsed.experiences, key=score).id or None

# 打包函数，转化为json格式
def _build_user_prompt(
    parsed: ResumeParsed, req: JDReq, risks: list[RiskItem]
) -> str:
    payload = {
        "parsed": parsed.model_dump(),
        "req": req.model_dump(),
        "risks": [
            {"risk_index": index, **risk.model_dump()}
            for index, risk in enumerate(risks)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)

# 越界题目和针对同一个风险的题目不要
def _valid_questions(questions: list[Question], risk_count: int) -> list[Question]:
    valid: list[Question] = []
    used: set[int] = set()
    for question in questions:
        if not 0 <= question.risk_index < risk_count:
            continue
        if question.risk_index in used:
            continue
        used.add(question.risk_index)
        valid.append(question)
    return valid

# 拷问主流程：规则找风险 → LLM 出题 → 校验并组装响应
def interrogate_resume(
    parsed: ResumeParsed, req: JDReq
) -> InterrogateResponse:
    raw = parsed.raw_text
    risks: list[RiskItem] = []

    for rule in scan_rules(parsed):
        span = locate_span(raw, rule.text, rule.start)
        if span is None:
            continue
        risks.append(
            RiskItem(
                type=rule.type,
                text=rule.text,
                reason=rule.reason,
                experience_id=rule.experience_id,
                start=span[0],
                end=span[1],
            )
        )

    if not risks:
        return InterrogateResponse(
            risks=[],
            questions=[],
            weakest_experience_id=_pick_weakest(parsed, []),
        )

    #
    result = model_json(
        system=PROMPT_PATH.read_text(encoding="utf-8"),
        user=_build_user_prompt(parsed, req, risks),
        schema=InterrogateResult,
    )

    questions = _valid_questions(result.questions, len(risks))
    if not questions:
        raise LLMOutputInvalid("模型没有生成有效的追问")

    experience_ids = {exp.id for exp in parsed.experiences if exp.id}
    weakest = result.weakest_experience_id
    if weakest not in experience_ids:
        weakest = _pick_weakest(parsed, risks)

    return InterrogateResponse(
        risks=risks,
        questions=questions,
        weakest_experience_id=weakest,
    )
