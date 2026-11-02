"""M4 规则点评的单元测试：不碰数据库、不碰 LLM，只验证判定顺序与话术。"""

import pytest

from app.services.qa_service import comment_for


@pytest.mark.parametrize("phrase", ["大概", "可能", "应该"])
def test_vague_phrase_points_to_missing_facts(phrase):
    comment = comment_for(f"我觉得{phrase}快了很多吧")

    assert "缺具体事实" in comment
    assert phrase in comment


def test_answer_without_metric_is_flagged():
    comment = comment_for("我优化了接口，效果很好，团队都很满意")

    assert "量化" in comment


def test_short_answer_with_metric_is_flagged_for_detail():
    comment = comment_for("QPS 从 300 提到 1200")

    assert "太短" in comment


def test_specific_long_answer_gets_positive_but_actionable_comment():
    answer = (
        "订单服务原先用 N+1 查询，压测 P99 480ms。我独立把热点商品改成批量查询并加 Redis 缓存，"
        "上线后 QPS 从 300 提到 1200，P99 降到 210ms。"
    )
    comment = comment_for(answer)

    assert "事实支撑" in comment
    assert "独立贡献" in comment


def test_priority_is_vague_before_short():
    """「大概吧」既短又模糊，按 FR-007 应先命中「缺具体事实」。"""
    comment = comment_for("大概吧")

    assert "缺具体事实" in comment
