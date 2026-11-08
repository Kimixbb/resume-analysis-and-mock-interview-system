"""M4 报告落库与回显：一个写事务、一个读联查。

存储格式不新增表/列，完全用 C 已经建好的三张表：
- `resume.parsed_json`、`jd.req_json` 存 M1 结果；
- `report.gaps` 存 M2 的三条差距（JSON 数组）；
- `report.risks` 按设计文档 6.2 存一个 JSON 对象：
  `{"risks": [...], "questions": [...], "weakest_experience_id": "proj_1"}`；
- `report.qa`、`report.rewrite` 由问答/重写接口分别更新。
"""

from __future__ import annotations

import json

from app.contracts.match import Gap
from app.contracts.parse import JDReq, ResumeParsed
from app.contracts.report_schema import (
    CreateReportRequest,
    CreateReportResponse,
    QaEntry,
    ReportDetailResponse,
    RewriteResponse,
)
from app.core.db import create_report as create_report_record
from app.core.db import get_jd, get_report, get_resume, get_session
from app.core.errors import InvalidInput
from app.services.report_guard import detect_resume_anomalies


def _dump(model) -> str:
    """把 Pydantic 模型（或模型列表）序列化成入库的 JSON 文本。"""
    if isinstance(model, list):
        payload = [
            item.model_dump() if hasattr(item, "model_dump") else item for item in model
        ]
    else:
        payload = model.model_dump() if hasattr(model, "model_dump") else model
    return json.dumps(payload, ensure_ascii=False)


def _load_list(raw: str | None) -> list:
    """反序列化入库的 JSON 数组；空值或脏数据统一退回空列表。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def load_interrogate(raw: str | None) -> dict:
    """从 report.risks 这一个字段里取出 M3 的三段结果。

    新格式是 `{risks, questions, weakest_experience_id}`；
    兼容早期只存 `risks` 数组的行（此时 questions 为空、最差经历为 None）。
    """
    empty = {"risks": [], "questions": [], "weakest_experience_id": None}
    if not raw:
        return empty
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return empty

    if isinstance(value, list):
        return {"risks": value, "questions": [], "weakest_experience_id": None}
    if not isinstance(value, dict):
        return empty

    risks = value.get("risks") if isinstance(value.get("risks"), list) else []
    questions = value.get("questions") if isinstance(value.get("questions"), list) else []
    weakest = value.get("weakest_experience_id")
    return {
        "risks": risks,
        "questions": questions,
        "weakest_experience_id": weakest if isinstance(weakest, str) else None,
    }


def _load_qa(raw: str | None) -> list[QaEntry] | None:
    """report.qa 允许为空；能解析就按契约校验，坏数据不让整个回显 500。"""
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, list):
            return None
        return [QaEntry.model_validate(item) for item in value]
    except (TypeError, ValueError):
        return None


def _load_rewrite(raw: str | None) -> RewriteResponse | None:
    """report.rewrite 允许为空；旧版 Mock 数据字段不全时不回显，避免 500。"""
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            return None
        return RewriteResponse.model_validate(value)
    except (TypeError, ValueError):
        return None


def create_report(data: CreateReportRequest) -> CreateReportResponse:
    """一次事务写 resume / jd / report 三张表，成功返回三个 id。

    任何一步失败都会由 get_session() 回滚并抛 DBError（500 DB_ERROR），
    不会留下只有简历和 JD、却没有报告的半成品。

    落库前先做一次「同一人」校验：把两份简历拼在一起时，M1/M2/M3 会把它
    当成一个候选人，所以这里必须在写库前拦下来（400 INVALID_INPUT）。
    """
    anomalies = detect_resume_anomalies(data.resume_text, data.parsed)
    if anomalies:
        raise InvalidInput(
            "简历信息可能不属于同一个人："
            + "；".join(anomalies)
            + "。请确认只提交一份简历后重试。"
        )

    # M3 的结果按设计文档 6.2 合并进 report.risks 一个字段
    risks_json = json.dumps(
        {
            "risks": [risk.model_dump() for risk in data.risks],
            "questions": [question.model_dump() for question in data.questions],
            "weakest_experience_id": data.weakest_experience_id,
        },
        ensure_ascii=False,
    )

    with get_session() as session:
        report = create_report_record(
            session,
            resume_text=data.resume_text,
            parsed_json=_dump(data.parsed),
            jd_text=data.jd_text,
            req_json=_dump(data.req),
            score=data.score,
            gaps_json=_dump(data.gaps),
            risks_json=risks_json,
        )
        session.flush()
        return CreateReportResponse(
            report_id=report.id,
            resume_id=report.resume_id,
            jd_id=report.jd_id,
        )


def get_report_by_id(report_id: int) -> ReportDetailResponse | None:
    """联查三表并反序列化 JSON 字段，返回前端可直接渲染的报告。"""
    with get_session() as session:
        report = get_report(session, report_id)
        if report is None:
            return None

        resume = get_resume(session, report.resume_id)
        jd = get_jd(session, report.jd_id)
        if resume is None or jd is None:
            # 外键数据缺失属于脏库，按「报告不存在」处理，避免 500 暴露内部细节。
            return None

        interrogate = load_interrogate(report.risks)

        return ReportDetailResponse(
            report_id=report.id,
            resume_text=resume.raw_text,
            parsed=ResumeParsed.model_validate_json(resume.parsed_json),
            jd_text=jd.raw_text,
            req=JDReq.model_validate_json(jd.req_json),
            score=report.score,
            gaps=[Gap.model_validate(item) for item in _load_list(report.gaps)],
            risks=interrogate["risks"],
            questions=interrogate["questions"],
            weakest_experience_id=interrogate["weakest_experience_id"],
            qa=_load_qa(report.qa),
            rewrite=_load_rewrite(report.rewrite),
            created_at=report.created_at.isoformat(sep=" ", timespec="seconds"),
        )
