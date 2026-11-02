"""M4 STAR 重写服务测试：复评分钳制、错误语义、Prompt 素材来源。"""

import json

import pytest

from app.contracts.report_schema import (
    STARData,
    RewriteOutput,
    clamp_improved_score,
)
from app.core import db
from app.core.errors import InvalidInput, NotFound
from app.services import rewrite_service


@pytest.mark.parametrize(
    ("score", "improved", "expected"),
    [
        (58, 40, 63),    # 低于原分 + 5 → 钳制到 63
        (58, 63, 63),    # 正好等于下限
        (58, 90, 90),    # 合法提升保持不动
        (98, 100, 100),  # 上限 100
        (100, 99, 100),  # 原分已满分，无法再涨
    ],
)
def test_clamp_improved_score(score, improved, expected):
    assert clamp_improved_score(score, improved) == expected


def test_rewrite_uses_resume_text_and_risks(seeded_report, report_payload, monkeypatch):
    """before 来自简历原文；Prompt 只带落在目标经历上的风险和 JD 关键词。"""
    captured: dict = {}

    def fake_model_json(*, system, user, schema, temperature=0.2):
        captured["system"] = system
        captured["user"] = json.loads(user)
        return RewriteOutput(
            after="[S] 背景 [T] 任务 [A] 行动 [R] 结果",
            star=STARData(S="背景", T="任务", A="行动", R="结果"),
            improved_score=70,
        )

    monkeypatch.setattr(rewrite_service, "model_json", fake_model_json)

    result = rewrite_service.generate_star_rewrite(seeded_report["report_id"])

    target = next(
        exp for exp in report_payload["parsed"]["experiences"]
        if exp["id"] == report_payload["weakest_experience_id"]
    )
    assert result.before == target["raw"]
    assert "STAR" in captured["system"]
    assert captured["user"]["experience"]["id"] == "proj_1"
    assert captured["user"]["jd"]["keywords"] == ["QPS", "P99", "缓存", "高并发"]
    # 风险按 experience_id 过滤，只保留 proj_1 的三条
    assert {risk["type"] for risk in captured["user"]["risks"]} == {"逻辑矛盾", "无数字", "空话"}
    assert len(captured["user"]["risks"]) == 3


def test_rewrite_persists_to_report(seeded_report, monkeypatch):
    monkeypatch.setattr(
        rewrite_service,
        "model_json",
        lambda **kwargs: RewriteOutput(
            after="[S] 背景 [T] 任务 [A] 行动 [R] 结果",
            star=STARData(S="背景", T="任务", A="行动", R="结果"),
            improved_score=80,
        ),
    )

    rewrite_service.generate_star_rewrite(seeded_report["report_id"])

    with db.get_session() as session:
        report = db.get_report(session, seeded_report["report_id"])
        stored = json.loads(report.rewrite)
    assert stored["improved_score"] == 80
    assert stored["after"].startswith("[S]")


def test_rewrite_missing_report_raises_not_found():
    with pytest.raises(NotFound):
        rewrite_service.generate_star_rewrite(99999)


def test_rewrite_unknown_experience_raises_invalid_input(seeded_report):
    with pytest.raises(InvalidInput):
        rewrite_service.generate_star_rewrite(seeded_report["report_id"], "not_exist")
