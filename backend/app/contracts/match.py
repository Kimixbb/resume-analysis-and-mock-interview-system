"""M2 匹配模块的请求、响应与 LLM 输出契约。"""

from pydantic import BaseModel, Field, model_validator

from app.contracts.parse import JDReq, ResumeParsed


class Gap(BaseModel):
    """一条有岗位依据、简历依据和解释的差距。"""

    jd: str = Field(min_length=1)
    resume: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class MatchDimensions(BaseModel):
    """可选的四个维度得分；设计文档未规定各项上限。"""

    hard_skill: int = Field(strict=True)
    project: int = Field(strict=True)
    metric: int = Field(strict=True)
    domain: int = Field(strict=True)


class MatchRequest(BaseModel):
    parsed: ResumeParsed
    req: JDReq

    @model_validator(mode="after")
    def check_content(self) -> "MatchRequest":
        if not self.parsed.raw_text.strip() and not any(
            (self.parsed.skills, self.parsed.experiences, self.parsed.metrics)
        ):
            raise ValueError("parsed 缺少简历内容")
        if not any((self.req.hard_skills, self.req.responsibilities, self.req.keywords)):
            raise ValueError("req 缺少岗位要求")
        return self


class MatchResult(BaseModel):
    """LLM 必须满足的结果；dimensions 不提供时允许省略。"""

    score: int = Field(strict=True, ge=0, le=100)
    gaps: list[Gap] = Field(min_length=3, max_length=3)
    dimensions: MatchDimensions | None = None


class MatchResponse(MatchResult):
    """POST /api/match 的响应。"""
