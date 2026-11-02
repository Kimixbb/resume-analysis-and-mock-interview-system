"""M4 逐题问答：后端按 question_index 取原题，规则点评，按题号覆盖写入。

这条链路不调 LLM（设计文档 §4.5.3 / FR-007），所以结果确定、可测试。
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.contracts.report_schema import QaEntry
from app.core.db import get_report, get_session, set_report_qa
from app.core.errors import InvalidInput, NotFound
from app.services.report_service import load_interrogate

# 「缺具体事实」的模糊表述词典（设计文档 §4.5.3）
VAGUE_PHRASES = ("大概", "可能", "应该")


def _has_metric(answer: str) -> bool:
    """回答里有没有数字或百分比——有才叫「量化」。"""
    return any(char.isdigit() for char in answer) or "%" in answer or "％" in answer


def comment_for(answer: str) -> str:
    """规则点评：一句点评，指出最需要补的那一点。

    优先级：模糊表述 > 缺量化 > 缺细节 > 有事实支撑。
    这样「大概吧」会先命中「缺具体事实」（FR-007 验收用例）。
    """
    for phrase in VAGUE_PHRASES:
        if phrase in answer:
            return (
                f"点评：回答里用了「{phrase}」这类模糊表述，缺具体事实，"
                "请给出可验证的时间、数字或场景。"
            )

    if not _has_metric(answer):
        return "点评：回答缺乏具体量化指标（无数字、无百分比），说服力不足，建议补上基线、结果和数据。"

    if len(answer.strip()) < 30:
        return "点评：回答太短，缺具体细节，面试官会认为你在回避问题，建议展开背景、行动和结果。"

    return "点评：回答有一定的事实支撑，但建议进一步突出你个人的独立贡献和可验证的结果。"


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


def evaluate_answer(report_id: int, question_index: int, answer: str) -> str:
    """按题号取原题 → 规则点评 → 同题覆盖写回 report.qa，返回一句点评。

    - 报告不存在 → 404 NOT_FOUND
    - 题号越界 → 400 INVALID_INPUT（回答长度由契约校验，同样 400）
    """
    with get_session() as session:
        report = get_report(session, report_id)
        if report is None:
            raise NotFound("报告不存在")

        # 报告里的追问在落库时已经固定（存在 report.risks 的 questions 里），
        # 这里只认后端存的原题
        questions = load_interrogate(report.risks)["questions"]

        if not 0 <= question_index < len(questions):
            raise InvalidInput(
                f"question_index 越界：报告只有 {len(questions)} 道题"
            )
        question = questions[question_index]
        question_text = question.get("text", "") if isinstance(question, dict) else ""

        comment = comment_for(answer)

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
