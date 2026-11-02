"""M4 接口：报告落库/回显、STAR 重写、逐题问答。

router 保持很薄：只做「收请求 → 调服务 → 还响应」，业务都在 services/ 里。
所有错误都用 core/errors.py 的 AppError 子类抛出，由 main.py 统一转成
{code, message}，不再混用 HTTPException 的 {detail} 格式。
"""

from fastapi import APIRouter

from app.contracts.report_schema import (
    CreateReportRequest,
    CreateReportResponse,
    QAResponse,
    QARequest,
    ReportDetailResponse,
    RewriteRequest,
    RewriteResponse,
)
from app.core.errors import NotFound
from app.services import qa_service, report_service, rewrite_service

router = APIRouter(prefix="/api", tags=["M4-Report & QA"])


@router.post(
    "/report",
    response_model=CreateReportResponse,
    responses={
        400: {"description": "嵌套模型不合法或 weakest_experience_id 不存在"},
        500: {"description": "数据库异常，事务已整体回滚"},
    },
)
def create_report_api(body: CreateReportRequest) -> CreateReportResponse:
    """汇总落库：原始文本 + M1/M2/M3 结果 → report_id / resume_id / jd_id。"""
    return report_service.create_report(body)


@router.get(
    "/report/{report_id}",
    response_model=ReportDetailResponse,
    responses={404: {"description": "报告不存在"}},
)
def get_report_api(report_id: int) -> ReportDetailResponse:
    """刷新回显：联查三表、反序列化 JSON，返回前端可直接渲染的聚合报告。"""
    data = report_service.get_report_by_id(report_id)
    if data is None:
        raise NotFound("报告不存在")
    return data


@router.post(
    "/rewrite",
    response_model=RewriteResponse,
    responses={
        400: {"description": "经历不存在或没有原文"},
        404: {"description": "报告不存在"},
        422: {"description": "LLM 输出缺 STAR 四要素"},
        500: {"description": "LLM 超时/网络异常"},
    },
)
def rewrite_experience(req: RewriteRequest) -> RewriteResponse:
    """STAR 重写：不传 experience_id 时用报告里的 weakest_experience_id。"""
    return rewrite_service.generate_star_rewrite(req.report_id, req.experience_id)


@router.post(
    "/qa",
    response_model=QAResponse,
    responses={
        400: {"description": "question_index 越界或 answer 不在 1–1000 字"},
        404: {"description": "报告不存在"},
        422: {"description": "LLM 点评为空或不符合契约"},
        500: {"description": "LLM 超时/网络异常或数据库更新失败"},
    },
)
def submit_qa(req: QARequest) -> QAResponse:
    """逐题问答：后端按 question_index 取原题，LLM 点评，同题覆盖写入。"""
    comment = qa_service.evaluate_answer(
        req.report_id, req.question_index, req.answer
    )
    return QAResponse(comment=comment)
