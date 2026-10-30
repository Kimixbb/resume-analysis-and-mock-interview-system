from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.parse import JDReq, ResumeParsed

RiskType = Literal["空话", "无数字", "逻辑矛盾"] #暂定三种风险类型


class RiskItem(BaseModel):
    type: RiskType
    text: str = Field(min_length=1) #被标红的文字
    reason: str = Field(min_length=1) #标红原因
    experience_id: str | None = None #经历编号
    start: int = Field(ge=0) #标红开始位置
    end: int = Field(ge=0) #标红结束位置

    #在创建对象字段填充后，检查 end 是否大于 start
    @model_validator(mode="after")
    def check_span(self) -> "RiskItem":
        if self.end <= self.start:
            raise ValueError("end 必须大于 start")
        return self


#追问
class Question(BaseModel):

    text: str = Field(min_length=1)
    risk_index: int = Field(ge=0)

#追问请求
class InterrogateRequest(BaseModel):

    parsed: ResumeParsed
    req: JDReq

    @model_validator(mode="after")
    def check_raw_text(self) -> "InterrogateRequest":
        if not self.parsed.raw_text.strip():
            raise ValueError("parsed 缺少 raw_text")
        return self


#追问结果
class InterrogateResult(BaseModel):

    questions: list[Question] = Field(min_length=1, max_length=5)
    weakest_experience_id: str | None = None

#追问响应
class InterrogateResponse(BaseModel):

    risks: list[RiskItem] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list, max_length=5)
    weakest_experience_id: str | None = None
