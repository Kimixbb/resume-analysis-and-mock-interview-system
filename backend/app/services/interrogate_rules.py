"""M3 规则层：用确定性规则找出三类风险，并给出原文偏移。

规则层只负责「找得到、定位准、可解释」，不调用 LLM。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts.interrogate import RiskType
from app.contracts.parse import ResumeParsed

# 空话关键词
BUZZWORDS = (
    "认真负责",
    "沟通能力强",
    "团队协作",
    "学习能力强",
    "抗压",
    "责任心强",
    "积极主动",
    "一致好评",
    "良好的沟通",
)

# 无量化关键词
VAGUE_WORDS = (
    "大幅",
    "显著",
    "明显",
    "极大",
    "全面提升",
    "有效",
    "一定程度",
    "较快",
)

METRIC = re.compile(r"\d|%|％|倍|qps|ms|万|亿", re.IGNORECASE)
CLAUSE = re.compile(r"[^，。；！？\n]+") # 用来切分句子的正则表达式
DATE_RANGE = re.compile(
    r"(?P<a>\d{4}[.\-/年]\d{1,2})\s*[-–—~至]\s*(?P<b>\d{4}[.\-/年]\d{1,2})"
)
DATE_PART = re.compile(r"(\d{4})[.\-/年](\d{1,2})")


@dataclass(frozen=True) # 冻结数据类，使其不可修改
class RuleRisk:
    type: RiskType
    text: str
    reason: str
    experience_id: str | None
    start: int
    end: int


def _clauses(raw: str):
    """按中文标点切句，保留每段在原文中的精确位置。"""
    for match in CLAUSE.finditer(raw):
        segment = match.group()
        left = len(segment) - len(segment.lstrip())
        text = segment.strip()
        if text:
            start = match.start() + left
            yield start, start + len(text), text

# 将日期转换为年月格式，如 2023-04-01 转换为 202304
def _to_ym(value: str) -> int | None:
    match = DATE_PART.search(value)
    if match is None:
        return None
    return int(match.group(1)) * 100 + int(match.group(2))


def _experience_for(parsed: ResumeParsed, start: int, end: int) -> str | None:
    """判断风险落在哪段经历里；找不到就返回 None。"""
    for experience in parsed.experiences:
        needle = experience.raw
        if not needle:
            continue
        pos = parsed.raw_text.find(needle)
        while pos != -1:
            if pos <= start and end <= pos + len(needle):
                return experience.id or None
            pos = parsed.raw_text.find(needle, pos + 1)
    return None


def scan_rules(parsed: ResumeParsed) -> list[RuleRisk]:
    """扫描空话、无数字、日期倒置三类风险，按原文顺序返回。"""
    raw = parsed.raw_text
    if not raw.strip():
        return []

    risks: list[RuleRisk] = []

    for start, end, text in _clauses(raw):
        if any(word in text for word in BUZZWORDS):
            risks.append(
                RuleRisk(
                    type="空话",
                    text=text,
                    reason="只有评价性形容词，没有具体事实或结果",
                    experience_id=_experience_for(parsed, start, end),
                    start=start,
                    end=end,
                )
            )

        if any(word in text for word in VAGUE_WORDS) and not METRIC.search(text):
            risks.append(
                RuleRisk(
                    type="无数字",
                    text=text,
                    reason="只有模糊程度描述，没有基线、数字或可验证结果",
                    experience_id=_experience_for(parsed, start, end),
                    start=start,
                    end=end,
                )
            )

    for match in DATE_RANGE.finditer(raw):
        begin = _to_ym(match.group("a"))
        finish = _to_ym(match.group("b"))
        if begin is None or finish is None or begin <= finish:
            continue
        risks.append(
            RuleRisk(
                type="逻辑矛盾",
                text=match.group(0),
                reason="起止时间倒置",
                experience_id=_experience_for(parsed, match.start(), match.end()),
                start=match.start(),
                end=match.end(),
            )
        )

    seen: set[tuple[str, int, int]] = set()
    unique: list[RuleRisk] = []
    for risk in sorted(risks, key=lambda item: (item.start, item.end, item.type)):
        key = (risk.type, risk.start, risk.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(risk)
    return unique
