import json
from app.core.db import get_session, get_report


def get_report_by_id(report_id: int) -> dict:
    # 使用 C 同学写的上下文管理器
    with get_session() as session:
        report = get_report(session, report_id)
        if not report:
            return None

        return {
            "id": report.id,
            "resume_id": report.resume_id,
            "jd_id": report.jd_id,
            "score": report.score,
            "gaps": json.loads(report.gaps),
            "risks": json.loads(report.risks),
            "qa": json.loads(report.qa) if report.qa else None,
            "rewrite": json.loads(report.rewrite) if report.rewrite else None
        }