"""M1 真实 LLM 集成测试（可选）——单元测试之外的「真枪实弹」。

和单测的区别：
- test_parse_service.py 等单测：model_json 被换成假实现，不联网、秒回；
- 这个文件：调真正的 LLM 服务，验证「Prompt + 模型 + 契约校验」整条链路。

运行规则：
- .env 里还是占位符（没填真实 Key/模型名）→ 整个文件自动 skip，
  不会拖慢也不会弄红 pytest；
- .env 填了真实配置 → 每个用例真实联网调一次 LLM（几秒、消耗少量 token）。

常用命令（在项目根目录执行）：
  pytest backend/tests/test_parse_integration.py -v -s  # -s 能看到模型原始输出
  pytest backend/tests                                  # 全部测试（没配 Key 时集成测试显示 skipped）
"""

from pathlib import Path

import pytest

from app.contracts.parse import ParseResponse
from app.core.config import settings
from app.services.parse_service import parse_resume

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# 占位符特征：.env 里还带着这些字样 = 还没填真实配置
_PLACEHOLDERS = ("把这里换成", "your-key", "your-model", "test-key")


def _llm_ready() -> bool:
    """判断 .env 是否已填好真实 LLM 配置（Key 和模型名都填了才算）。"""
    key = settings.openai_api_key.strip()
    model = settings.openai_model.strip()
    if not key or not model:
        return False
    return not any(word in key or word in model for word in _PLACEHOLDERS)


# 整个文件级的跳过开关：没配好就全部 skip，pytest 依旧全绿
pytestmark = pytest.mark.skipif(
    not _llm_ready(),
    reason=".env 里还是占位符（未配置真实 LLM），填好 Key 和模型名后自动启用",
)


def _read(name: str) -> str:
    """读 fixtures 里的文本文件。"""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _assert_contract(result: ParseResponse, resume_text: str) -> None:
    """真实输出同样必须满足 M1 契约（单测用假数据验证过，这里用真数据复检）。

    注意：LLM 每次输出的具体内容都可能不同，所以只断言「结构」，
    不比较和 fixtures/parsed.json 的逐字内容。
    """
    assert result.parsed.raw_text == resume_text  # 契约红线：原文一字不差
    ids = [e.id for e in result.parsed.experiences]
    assert len(ids) == len(set(ids)), "经历 id 必须唯一"
    for exp in result.parsed.experiences:
        assert exp.id, "经历 id 不能为空"
        assert exp.raw.strip(), "每段经历都要有原文摘录（M3 靠它定位标红）"
    assert result.req.hard_skills, "JD 里至少应抽出一些硬技能"
    assert isinstance(result.req.min_years, int) and result.req.min_years >= 0


def test_real_llm_parse_bad_resume():
    """坏简历（含空话/无数字/日期倒置）真实解析一遍。"""
    resume = _read("resume_bad.txt")
    jd = _read("jd_backend.txt")

    result = parse_resume(resume, jd)

    _assert_contract(result, resume)
    print("\n=== 真实 LLM 输出（resume_bad）===")
    print(result.model_dump_json(indent=2, ensure_ascii=False))


def test_real_llm_parse_good_resume():
    """干净简历（量化数据齐全）真实解析一遍。"""
    resume = _read("resume_good.txt")
    jd = _read("jd_backend.txt")

    result = parse_resume(resume, jd)

    _assert_contract(result, resume)
    print("\n=== 真实 LLM 输出（resume_good）===")
    print(result.model_dump_json(indent=2, ensure_ascii=False))
