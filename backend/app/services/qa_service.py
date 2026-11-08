"""M4 逐题问答：后端按 question_index 取原题，调 LLM 生成点评，按题号覆盖写入。

设计文档 §4.5.3 / §5.1（v1.1）把点评从「规则判断」改成「LLM 生成」：
Prompt 输入原题、用户回答、对应风险与岗位关键词，要求给出一句具体、
可执行的改进建议；comment 非空，模型输出非法 → 422，超时/网络异常 → 500。
接口超时 30s：LLM 调用统一走 core/llm.py，用的是 settings.llm_timeout（默认 30）。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.contracts.parse import JDReq
from app.contracts.report_schema import QACommentOutput, QaEntry
from app.core.db import get_jd, get_report, get_session, set_report_qa
from app.core.errors import InvalidInput, LLMOutputInvalid, NotFound
from app.core.llm import model_json
from app.services.report_service import load_interrogate

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa.md"


def _load_entries(raw: str | None) -> list[QaEntry]:
    """读取已有的问答记录；旧版无 question_index 的脏数据直接忽略。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    entries: list[QaEntry] = []
    for item in value:
        try:
            entries.append(QaEntry.model_validate(item))
        except ValidationError:
            continue
    return entries


def _risk_for(question: dict, risks: list[dict]) -> dict | None:
    """按 question.risk_index 找到这道题对应的风险；越界或缺失就返回 None。"""
    index = question.get("risk_index")
    if isinstance(index, int) and 0 <= index < len(risks):
        return risks[index]
    return None


def _build_user_prompt(
    *, question: dict, answer: str, risk: dict | None, req: JDReq | None
) -> str:
    """只喂和这次点评相关的材料：题目、回答、对应风险、岗位关键词。"""
    payload = {
        "question": question.get("text", ""),
        "answer": answer,
        "risk": {
            "type": risk.get("type", ""),
            "text": risk.get("text", ""),
            "reason": risk.get("reason", ""),
        }
        if risk
        else None,
        "jd_keywords": req.keywords if req else [],
        "jd_requirements": req.hard_skills if req else [],
    }
    return json.dumps(payload, ensure_ascii=False)


def evaluate_answer(report_id: int, question_index: int, answer: str) -> str:
    """按题号取原题 → LLM 点评 → 同题覆盖写回 report.qa，返回一句点评。

    - 报告不存在 → 404 NOT_FOUND
    - 题号越界 → 400 INVALID_INPUT（回答长度由契约校验，同样 400）
    - LLM 输出空点评/不合契约 → 422；超时或网络异常 → 500
    """
    with get_session() as session:
        report = get_report(session, report_id)
        if report is None:
            raise NotFound("报告不存在")

        # 报告里的追问在落库时已经固定（存在 report.risks 的 questions 里），
        # 这里只认后端存的原题
        interrogate = load_interrogate(report.risks)
        questions = interrogate["questions"]

        if not 0 <= question_index < len(questions):
            raise InvalidInput(
                f"question_index 越界：报告只有 {len(questions)} 道题"
            )
        question = questions[question_index]
        if not isinstance(question, dict):
            raise LLMOutputInvalid("报告里的追问记录不合法")
        question_text = question.get("text", "")

        jd = get_jd(session, report.jd_id)
        req = JDReq.model_validate_json(jd.req_json) if jd is not None else None

        result = model_json(
            system=PROMPT_PATH.read_text(encoding="utf-8"),
            user=_build_user_prompt(
                question=question,
                answer=answer,
                risk=_risk_for(question, interrogate["risks"]),
                req=req,
            ),
            schema=QACommentOutput,
        )
        comment = result.comment.strip()
        if not comment:
            raise LLMOutputInvalid("模型点评为空")

        # 同题重复提交按覆盖，不追加第二条（FR-007）；按题号排序保持题序
        entries = [
            entry for entry in _load_entries(report.qa)
            if entry.question_index != question_index
        ]
        entries.append(
            QaEntry(
                question_index=question_index,
                question=question_text,
                answer=answer,
                comment=comment,
            )
        )
        entries.sort(key=lambda entry: entry.question_index)

        payload = json.dumps(
            [entry.model_dump() for entry in entries], ensure_ascii=False
        )
        if set_report_qa(session, report_id, payload) is None:
            raise NotFound("报告不存在")

        return comment
