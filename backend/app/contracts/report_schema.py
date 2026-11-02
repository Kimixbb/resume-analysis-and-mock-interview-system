"""M4 数据契约：报告落库与回显、逐题问答、STAR 重写。

一个文件管三块接口（对齐设计文档 §5.5–§5.8）：
- POST /api/report            汇总落库：原始文本 + M1/M2/M3 结果 → 三个 id
- GET  /api/report/{report_id} 联查三表、反序列化 JSON → 前端可渲染结构
- POST /api/qa                按 question_index 取原题、LLM 点评、覆盖写入
- POST /api/rewrite           STAR 重写：before 来自简历原文，after/star 来自 LLM
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.interrogate import Question, RiskItem
from app.contracts.match import Gap
from app.contracts.parse import JDReq, ResumeParsed

# ----------------- 重写 (Rewrite) 相关 -----------------


def clamp_improved_score(score: int, improved: int) -> int:
    """复评分必须严格大于原分：低于原分 + 5 时钳制为原分 + 5，上限 100。

    原分已经是 100 时无法再提高，直接返回 100（FR-006 的边界情况）。
    """
    if score >= 100:
        return 100
    return min(100, max(improved, score + 5))


class RewriteRequest(BaseModel):
    """POST /api/rewrite 的请求体（设计文档 §5.7）。"""

    report_id: int
    # 不传就用报告里存的 weakest_experience_id，不要写死 proj_1
    experience_id: Optional[str] = None


class STARData(BaseModel):
    """STAR 四要素，缺任意一个都视为 LLM 输出不合契约（422）。"""

    S: str = Field(min_length=1, description="情境")
    T: str = Field(min_length=1, description="任务")
    A: str = Field(min_length=1, description="行动")
    R: str = Field(min_length=1, description="结果")


class RewriteOutput(BaseModel):
    """LLM 只负责改写文本和复评分；before 由后端从简历原文取，不让模型改。"""

    after: str = Field(min_length=1, description="改写后的 STAR 文本")
    star: STARData
    improved_score: int = Field(ge=0, le=100)


class RewriteResponse(BaseModel):
    """POST /api/rewrite 的响应体（设计文档 §5.7）。"""

    before: str
    after: str
    star: STARData
    improved_score: int


# ----------------- 问答 (QA) 相关 -----------------


class QARequest(BaseModel):
    """POST /api/qa 的请求体（设计文档 §5.8）。

    前端只传题号，不传问题文本：后端按 question_index 从报告里取原题，
    防止前端把题目文本改掉或与报告对不上。
    """

    report_id: int
    question_index: int = Field(ge=0, description="题目下标，从 0 开始")
    answer: str = Field(min_length=1, max_length=1000, description="用户回答，1–1000 字")

    @model_validator(mode="after")
    def check_answer_not_blank(self) -> "QARequest":
        if not self.answer.strip():
            raise ValueError("回答不能为空")
        return self


class QaEntry(BaseModel):
    """report.qa 里的一条记录；同一题重复提交按 question_index 覆盖。"""

    question_index: int
    question: str
    answer: str
    comment: str


class QACommentOutput(BaseModel):
    """LLM 点评输出：只给一句 comment。

    设计文档 §4.5.3（v1.1）：点评改由 LLM 生成，空点评或全空白视为
    模型输出不合契约（422）。
    """

    comment: str = Field(min_length=1, max_length=500)

    @field_validator("comment")
    @classmethod
    def check_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("点评不能为空")
        return text


class QAResponse(BaseModel):
    """POST /api/qa 的响应体 = {comment}。"""

    comment: str


# ----------------- 报告 (Report) 通用响应 -----------------


class CreateReportRequest(BaseModel):
    """POST /api/report 的请求体（设计文档 §5.5）。

    前端把「原始文本 + M1 的 parsed/req + M2 的 score/gaps + M3 的
    risks/questions/weakest_experience_id」一次性交上来，后端只做校验和落库。
    """

    resume_text: str = Field(min_length=1)
    jd_text: str = Field(min_length=1)
    parsed: ResumeParsed
    req: JDReq
    score: int = Field(ge=0, le=100, description="M2 的 0–100 匹配分")
    gaps: List[Gap] = Field(min_length=3, max_length=3, description="恰好 3 条差距")
    risks: List[RiskItem] = Field(default_factory=list)
    questions: List[Question] = Field(default_factory=list, max_length=5)
    weakest_experience_id: Optional[str] = None

    @model_validator(mode="after")
    def check_weakest_exists(self) -> "CreateReportRequest":
        """最差经历必须真的在 parsed.experiences 里，否则重写会找不到原文。"""
        if self.weakest_experience_id is None:
            return self
        experience_ids = {exp.id for exp in self.parsed.experiences if exp.id}
        if self.weakest_experience_id not in experience_ids:
            raise ValueError("weakest_experience_id 不在 parsed.experiences 中")
        return self


class CreateReportResponse(BaseModel):
    """POST /api/report 的响应体：三个 id，后续问答/重写都用 report_id。"""

    report_id: int
    resume_id: int
    jd_id: int


class ReportDetailResponse(BaseModel):
    """GET /api/report/{report_id} 的响应体（设计文档 §5.6）。

    report_id 是报告主键（不叫 id）；同时带回 resume_text / parsed /
    jd_text / req，刷新页面后无需重跑 parse。
    """

    report_id: int
    resume_text: str
    parsed: ResumeParsed
    jd_text: str
    req: JDReq
    score: int
    gaps: List[Gap]
    risks: List[RiskItem]
    questions: List[Question]
    weakest_experience_id: Optional[str] = None
    qa: Optional[List[QaEntry]] = None
    rewrite: Optional[RewriteResponse] = None
    created_at: str


__all__ = [
    "STARData",
    "RewriteRequest",
    "RewriteOutput",
    "RewriteResponse",
    "QARequest",
    "QaEntry",
    "QAResponse",
    "CreateReportRequest",
    "CreateReportResponse",
    "ReportDetailResponse",
    "clamp_improved_score",
]
