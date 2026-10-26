"""M1 解析模块的数据契约：接口入参/出参 + LLM 输出结构。

契约文件只定义「数据长什么样」，不写业务逻辑。
`parsed` 和 `req` 是跨模块结构：M2（匹配）、M3（拷问）都吃这两个对象。
字段以 fixtures/parsed.json 为准，改字段要先和 B/C/D 对齐。
"""

from pydantic import BaseModel, Field


class Experience(BaseModel):
    """一段经历（项目 / 工作 / 实习），M3 标红和追问都靠 raw 原文定位。"""

    id: str = ""  # 唯一编号，如 proj_1；LLM 忘了填时后端会自动补
    kind: str = "other"  # 类型：project / work / intern / other
    title: str = ""  # 项目名或职位名
    org: str = ""  # 公司或组织
    start: str = ""  # 开始时间，尽量 YYYY-MM
    end: str = ""  # 结束时间，尽量 YYYY-MM
    raw: str = ""  # 这段经历在简历里的原文（原样摘录，不改写）
    bullets: list[str] = Field(default_factory=list)  # 做过的事，一条一句
    metrics: list[str] = Field(default_factory=list)  # 这段里的量化数据


class Education(BaseModel):
    """一条教育经历。"""

    school: str = ""
    major: str = ""
    start: str = ""
    end: str = ""
    degree: str = ""  # 学历，如 本科


class ResumeParsed(BaseModel):
    """简历解析结果（M1 的核心输出之一）。"""

    raw_text: str = ""  # 简历原文；LLM 不需要返回（prompt 明确不要求），后端用请求原文覆盖
    skills: list[str] = Field(default_factory=list)  # 技能清单
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)  # 整份简历的量化数据


class JDReq(BaseModel):
    """岗位 JD 的结构化要求（M1 的另一个核心输出）。"""

    hard_skills: list[str] = Field(default_factory=list)  # 硬性技能要求
    responsibilities: list[str] = Field(default_factory=list)  # 岗位职责
    keywords: list[str] = Field(default_factory=list)  # 关键词，如 QPS、缓存
    min_years: int = 0  # 最低年限，JD 没写就是 0


class ParseResult(BaseModel):
    """LLM 一次调用要吐出来的整体 JSON = {parsed, req}。

    注意 LLM 只负责除 raw_text 外的字段；raw_text 由后端用请求原文覆盖。
    """

    parsed: ResumeParsed
    req: JDReq


class ParseRequest(BaseModel):
    """POST /api/parse 的请求体（设计文档 5.2）。"""

    resume_text: str  # 简历纯文本
    jd_text: str  # JD 纯文本


class ParseResponse(BaseModel):
    """POST /api/parse 的响应体 = {parsed, req}。"""

    parsed: ResumeParsed
    req: JDReq
