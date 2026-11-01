"""M3 规则层：三类风险、原文偏移和经历归属。"""

from pathlib import Path

from app.contracts.parse import ParseResponse, ResumeParsed
from app.services.interrogate_rules import scan_rules

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _parsed() -> ResumeParsed:
    source = ParseResponse.model_validate_json(
        (FIXTURES / "parsed.json").read_text(encoding="utf-8")
    )
    return source.parsed


def test_scan_rules_finds_all_three_types():
    parsed = _parsed()
    risks = scan_rules(parsed)

    assert len(risks) == 4
    assert {risk.type for risk in risks} == {"空话", "无数字", "逻辑矛盾"}

    for risk in risks:
        assert parsed.raw_text[risk.start : risk.end] == risk.text


def test_scan_rules_assigns_experience_ids():
    parsed = _parsed()
    by_text = {risk.text: risk for risk in scan_rules(parsed)}

    assert by_text["2024.09-2024.06"].experience_id == "proj_1"
    assert by_text["大幅提升了系统性能"].experience_id == "proj_1"
    assert by_text["认真负责、沟通能力强"].experience_id == "proj_1"
    assert by_text["获得一致好评"].experience_id == "work_1"


def test_clean_resume_has_no_risks():
    parsed = ResumeParsed(
        raw_text="2023.01-2023.12 某项目\nQPS 从 100 提升到 200。"
    )
    assert scan_rules(parsed) == []


def test_reversed_dates_are_reported():
    parsed = ResumeParsed(raw_text="2025.01-2024.01 某项目\n负责后端开发。")
    risks = scan_rules(parsed)

    assert [(risk.type, risk.text) for risk in risks] == [
        ("逻辑矛盾", "2025.01-2024.01")
    ]
    risk = risks[0]
    assert parsed.raw_text[risk.start : risk.end] == "2025.01-2024.01"
