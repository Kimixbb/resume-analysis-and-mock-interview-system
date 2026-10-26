"""M1 解析服务：把简历文本 + JD 文本转成结构化 JSON。

这是整条诊断链路的起点：这里产出的 parsed 和 req，
是后面 M2（匹配打分）和 M3（风险拷问）的输入。
"""

from pathlib import Path

from app.contracts.parse import ParseResult, ParseResponse, ResumeParsed
from app.core.errors import InvalidInput
from app.core.llm import model_json

# 长度规则来自需求文档 FR-001：按 strip 后的长度校验，超出上限就截断
RESUME_MIN, RESUME_MAX = 100, 8000
JD_MIN, JD_MAX = 50, 8000

# prompt 模板：services/ 的上一层是 app/，prompts 放在 app/prompts/ 下
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "parse.md"


def _system_prompt() -> str:
    """读 prompt 模板文件（文件很小，每次现读即可）。"""
    return PROMPT_PATH.read_text(encoding="utf-8")


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
