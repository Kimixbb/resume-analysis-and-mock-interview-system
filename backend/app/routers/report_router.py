from fastapi import APIRouter, HTTPException
from app.contracts.report_schema import (
    ReportDetailResponse,
    RewriteRequest,
    RewriteResponse,
    QARequest,
    QAResponse
)
from app.services import report_service, rewrite_service, qa_service

router = APIRouter(prefix="/api", tags=["M4-Report & QA"])

@router.get("/report/{report_id}", response_model=ReportDetailResponse)
def get_report_api(report_id: int):
    data = report_service.get_report_by_id(report_id)
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")
    return data

@router.post("/rewrite", response_model=RewriteResponse)
def rewrite_experience(req: RewriteRequest):
    data = rewrite_service.generate_star_rewrite(req.report_id, req.experience_id)
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")
    return data

@router.post("/qa", response_model=QAResponse)
def submit_qa(req: QARequest):
    comment = qa_service.evaluate_answer(req.report_id, req.question, req.answer)
    return {"comment": comment}