from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

# ----------------- 重写 (Rewrite) 相关 -----------------
class RewriteRequest(BaseModel):
    report_id: int
    experience_id: Optional[str] = "proj_1" # 默认重写最差经历

class STARData(BaseModel):
    S: str = Field(description="情境")
    T: str = Field(description="任务")
    A: str = Field(description="行动")
    R: str = Field(description="结果")

class RewriteResponse(BaseModel):
    before: str
    after: str
    star: STARData
    improved_score: int

# ----------------- 问答 (QA) 相关 -----------------
class QARequest(BaseModel):
    report_id: int
    question: str
    answer: str

class QAResponse(BaseModel):
    comment: str

# ----------------- 报告 (Report) 通用响应 -----------------
class ReportDetailResponse(BaseModel):
    id: int
    resume_id: int
    jd_id: int
    score: int
    gaps: List[Dict[str, Any]]
    risks: List[Dict[str, Any]]
    qa: Optional[List[Dict[str, Any]]] = None
    rewrite: Optional[Dict[str, Any]] = None