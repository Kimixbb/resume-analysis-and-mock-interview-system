"""M1 解析服务：把简历文本 + JD 文本转成结构化 JSON。

这是整条诊断链路的起点：这里产出的 parsed 和 req，
是后面 M2（匹配打分）和 M3（风险拷问）的输入。
"""

from pathlib import Path
import re

from app.contracts.parse import ParseResult, ParseResponse, ResumeParsed
from app.core.errors import InvalidInput
from app.core.llm import model_json

# 长度规则来自需求文档 FR-001：按 strip 后的长度校验，超出上限就截断
RESUME_MIN, RESUME_MAX = 100, 8000
JD_MIN, JD_MAX = 50, 8000

# 多份简历的强信号：多个邮箱/手机号，或重复出现核心栏目
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
RESUME_SECTIONS = (
    "教育经历",
    "项目经历",
    "实习经历",
    "工作经历",
    "求职意向",
    "个人信息",
    "联系方式",
)

# prompt 模板：services/ 的上一层是 app/，prompts 放在 app/prompts/ 下
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "parse.md"


def _system_prompt() -> str:
    """读 prompt 模板文件（文件很小，每次现读即可）。"""
    return PROMPT_PATH.read_text(encoding="utf-8")


def _looks_like_multiple_resumes(text: str) -> bool:
    """用确定性信号判断用户是否一次粘贴了多份简历。

    强信号：
    - 出现两个及以上不同邮箱；
    - 出现两个及以上不同手机号；
    - 「教育经历」「求职意向」「个人信息」等核心栏目重复出现；
    - 至少两类栏目同时重复出现。

    不做姓名识别，避免把同一个人的多个「姓名：」写法误判。
    """
    emails = {match.group(0).lower() for match in EMAIL_RE.finditer(text)}
    if len(emails) >= 2:
        return True

    # 去掉手机号里的空格、横线和括号后再匹配，兼容 138-0000-0000 这种写法
    digits_only = re.sub(r"[\s\-()+]", "", text)
    phones = {match.group(0) for match in MOBILE_RE.finditer(digits_only)}
    if len(phones) >= 2:
        return True

    counts = {section: text.count(section) for section in RESUME_SECTIONS}
    if any(counts[section] >= 2 for section in ("教育经历", "求职意向", "个人信息")):
        return True

    repeated_sections = [section for section, count in counts.items() if count >= 2]
    return len(repeated_sections) >= 2


def _check_text(text: str, *, name: str, min_len: int, max_len: int) -> str:
    """校验并规整一段输入文本。

    - 为空 / 全是空白 / strip 后不足 min_len → 抛 400（INVALID_INPUT）；
    - 超过 max_len → 静默截断（FR-001：超出截断）；
    - 返回的是后续环节（拼 Prompt、写 raw_text）统一使用的文本。
    """
    if not text or not text.strip():
        raise InvalidInput(f"{name}内容不能为空")
    if len(text.strip()) < min_len:
        raise InvalidInput(f"{name}字数不足{min_len}字")
    if len(text) > max_len:
        return text[:max_len]
    return text


def _ensure_experience_ids(parsed: ResumeParsed) -> None:
    """保证每条经历的 id 唯一且非空。

    LLM 可能忘填 id 或填重复，而 M3/M4 要用 id 定位经历，
    所以在后端统一兜底：缺了或重复就自动编一个 exp_1、exp_2……
    """
    used: set[str] = set()  # 已经被占用的 id
    counter = 1  # 自动编号从 1 开始
    for exp in parsed.experiences:
        if exp.id and exp.id not in used:  # 原本就有合法 id 的，保留不动
            used.add(exp.id)
            continue
        while f"exp_{counter}" in used:  # 跳过已被占用的编号
            counter += 1
        exp.id = f"exp_{counter}"
        used.add(exp.id)


def parse_resume(resume_text: str, jd_text: str) -> ParseResponse:
    """M1 主流程：两段文本进，parsed + req 出。

    步骤：校验输入 → 拼 Prompt 调 LLM → 用真实原文覆盖 raw_text → 补经历 id。
    LLM 输出非法会抛 LLMOutputInvalid(422)，超时会抛 LLMUpstreamError(500)，
    这两个异常这里不捕获，交给 main.py 统一转成 {code, message} 响应。
    """
    if _looks_like_multiple_resumes(resume_text):
        raise InvalidInput("检测到多份简历，请一次只粘贴一份简历")
    resume_text = _check_text(
        resume_text, name="简历", min_len=RESUME_MIN, max_len=RESUME_MAX
    )
    jd_text = _check_text(jd_text, name="JD", min_len=JD_MIN, max_len=JD_MAX)

    # 把简历和 JD 拼进 user 消息；输出格式由 prompt 里的模板约束
    user_prompt = f"【简历】\n{resume_text}\n\n【岗位JD】\n{jd_text}"
    result = model_json(system=_system_prompt(), user=user_prompt, schema=ParseResult)

    # 契约要求 parsed.raw_text 与请求的 resume_text 完全一致，
    # 不能指望 LLM 原样带回大段文本，所以后端直接覆盖。
    result.parsed.raw_text = resume_text
    _ensure_experience_ids(result.parsed)

    return ParseResponse(parsed=result.parsed, req=result.req)
