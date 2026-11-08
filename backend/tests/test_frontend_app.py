"""前端（Streamlit）端到端测试：用 AppTest 跑真实页面 + 真实后端（TestClient）。

做法：
- 后端不再 mock 服务层，只把 LLM 换成 fixtures 假实现（由 fake_llm fixture 负责），
  所以 parse → match ∥ interrogate → report → qa → rewrite 都是真逻辑；
- 把 `requests` 换成转发到 `TestClient` 的假模块（conftest 的 apptest_client），
  页面代码零改动；
- 输入用 fixtures 里的坏简历/真 JD，M3 的规则层才能真的扫出风险和追问。
"""

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _resume() -> str:
    return (FIXTURES / "resume_bad.txt").read_text(encoding="utf-8")


def _jd() -> str:
    return (FIXTURES / "jd_backend.txt").read_text(encoding="utf-8")


def _fill_and_diagnose(at):
    at.text_area(key="resume_input").input(_resume())
    at.text_area(key="jd_input").input(_jd())
    at.button(key="diagnose_button").click().run()
    return at


def test_page_renders_without_report(apptest_client, fake_llm):
    at = apptest_client()

    assert not at.exception
    assert [header.value for header in at.header] == [
        "📝 简历与 JD 输入",
        "🔍 匹配分与风险拷问",
        "☠️ 致命追问",
        "✨ STAR 重写",
    ]
    assert "等待诊断结果 ..." in [info.value for info in at.info]


def test_diagnosis_chain_shows_score_gaps_and_questions(apptest_client, fake_llm):
    at = apptest_client()
    _fill_and_diagnose(at)

    assert not at.exception
    assert at.metric[0].value == "58 / 100"
    markdown_text = " ".join(element.value for element in at.markdown)
    assert any("三条关键差距" in heading.value for heading in at.subheader)
    assert "3 年以上后端开发经验" in markdown_text
    assert "大幅提升了系统性能" in markdown_text
    assert "Q1 / 4" in markdown_text


def test_mixed_resume_is_blocked_before_request(apptest_client):
    """两份简历拼在一起时，前端应在发请求前就拦下。"""
    at = apptest_client()
    at.text_area(key="resume_input").input(
        "张三 | 138-0000-0000 | zhangsan@example.com\n"
        "【工作经历】某科技公司 产品经理（2022.07-至今），负责用户增长，转化率提升 15%。\n"
        "李四 | 应届毕业生 | 新闻学专业\n"
        "【实习经历】某传媒公司 新媒体运营实习生（2023.06-2023.09），公众号粉丝 5000→15000。\n"
        + "补充说明：" + "内容" * 40
    )
    at.text_area(key="jd_input").input("岗位 JD " * 10)
    at.button(key="diagnose_button").click().run()

    assert not at.exception
    assert any("多个姓名" in element.value for element in at.error)
    assert len(at.metric) == 0


def test_qa_one_question_at_a_time(apptest_client, fake_llm):
    at = apptest_client()
    _fill_and_diagnose(at)

    # 页面上只出现当前这一题的输入框
    qa_areas = [area for area in at.text_area if area.key and area.key.startswith("qa_answer_")]
    assert len(qa_areas) == 1
    assert "Q1 / 4" in " ".join(element.value for element in at.markdown)

    # 提交第一题 → 出现点评，并自动进入第二题
    qa_areas[0].input("大概吧")
    at.button(key="FormSubmitter:qa_form_0-提交点评").click().run()

    assert not at.exception
    assert any("缺具体事实" in info.value for info in at.info)
    assert "Q2 / 4" in " ".join(element.value for element in at.markdown)


def test_rewrite_panel_renders_before_and_after(apptest_client, fake_llm):
    at = apptest_client()
    _fill_and_diagnose(at)

    # 给 rewrite 服务补一个假 LLM（fake_llm 只接了 M1/M2/M3）
    from app.contracts.report_schema import RewriteOutput, STARData
    from app.services import rewrite_service

    original = rewrite_service.model_json
    rewrite_service.model_json = lambda **kwargs: RewriteOutput(
        after="[S] 背景 [T] 任务 [A] 行动 [R] 结果：P99 降到 210ms",
        star=STARData(S="背景", T="任务", A="行动", R="P99 降 56%"),
        improved_score=70,
    )
    try:
        at.button(key="rewrite_button").click().run()
    finally:
        rewrite_service.model_json = original

    assert not at.exception
    assert "改后（可直接复制）" in [area.label for area in at.text_area]
    rewrite_after = next(
        area for area in at.text_area if area.label == "改后（可直接复制）"
    )
    assert rewrite_after.value.startswith("[S]")
    assert any("重写后预估得分" in element.value for element in at.success)
