"""M4 输入一致性校验的单元测试：多姓名、履历重叠、应届冲突与正常简历。"""

import json
from pathlib import Path

from app.contracts.parse import Education, Experience, ResumeParsed
from app.services.report_guard import (
    detect_candidate_names,
    detect_input_swap,
    detect_resume_anomalies,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

JD_LIKE_TEXT = """招聘：财务专员/总账会计
【岗位职责】
负责公司全盘账务处理，包括凭证审核、记账、结账等；
按时编制财务报表并进行基础财务分析；
负责税务申报、发票管理及年度汇算清缴工作；
配合外部审计工作，提供相关财务资料。
【任职要求】
会计学本科及以上，持有初级会计师证优先。
"""

RESUME_LIKE_TEXT = """王五 | 会计学本科 | 持有初级会计师证
【工作经历】
某贸易有限公司 | 财务助理 (2020.03 - 2023.12)
负责日常费用报销审核、凭证录入及装订，保证账务处理的准确性。
"""

MIXED_TEXT = (
    "张三 | 138-0000-0000 | zhangsan@example.com\n"
    "【教育背景】某大学 计算机科学与技术 本科（2018-2022）\n"
    "【工作经历】某科技公司 产品经理（2022.07-至今）\n"
    "负责用户增长，转化率提升 15%。\n"
    "李四 | 应届毕业生 | 新闻学专业\n"
    "【校园经历】校学生会宣传部部长，公众号粉丝 5000→15000。\n"
    "【实习经历】某传媒公司 新媒体运营实习生（2023.06-2023.09）\n"
)


def _mixed_parsed() -> ResumeParsed:
    return ResumeParsed(
        raw_text=MIXED_TEXT,
        experiences=[
            Experience(
                id="work_1", kind="work", title="产品经理",
                start="2022-07", end="至今",
            ),
            Experience(
                id="intern_1", kind="intern", title="新媒体运营实习生",
                start="2023-06", end="2023-09",
            ),
        ],
        education=[Education(school="某大学", start="2020-09", end="2024-06", degree="本科")],
    )


def test_single_name_resume_has_no_name_anomaly():
    text = (FIXTURES / "resume_bad.txt").read_text(encoding="utf-8")

    assert detect_candidate_names(text) == ["张三"]


def test_two_names_are_detected():
    names = detect_candidate_names(MIXED_TEXT)

    assert names[:2] == ["张三", "李四"]


def test_section_headings_are_not_treated_as_names():
    text = "教育经历\n工作经历\n项目经历\n技能\n获奖 | 一等奖\n证书 | CET-6\n"

    assert detect_candidate_names(text) == []


def test_name_label_is_detected():
    assert detect_candidate_names("姓名：王五\n电话：138") == ["王五"]


def test_mixed_resume_reports_all_anomalies():
    anomalies = detect_resume_anomalies(MIXED_TEXT, _mixed_parsed())

    joined = "；".join(anomalies)
    assert "多个姓名" in joined
    assert "全职工作与实习时间重叠" in joined
    assert "在校时间与全职工作重叠" in joined
    assert "应届" in joined


def test_normal_resume_has_no_anomaly():
    payload = json.loads((FIXTURES / "parsed.json").read_text(encoding="utf-8"))
    parsed = ResumeParsed.model_validate(payload["parsed"])
    text = (FIXTURES / "resume_bad.txt").read_text(encoding="utf-8")

    assert detect_resume_anomalies(text, parsed) == []


def test_swapped_inputs_are_detected():
    """简历框放 JD、JD 框放简历：必须识别出来。"""
    # 第一个参数是「简历框」里的内容 = JD 文本；第二个是「JD 框」里的内容 = 简历文本
    message = detect_input_swap(JD_LIKE_TEXT, RESUME_LIKE_TEXT)

    assert message is not None
    assert "填反" in message
    assert "岗位职责" in message


def test_correct_inputs_are_not_flagged_as_swapped():
    resume = (FIXTURES / "resume_bad.txt").read_text(encoding="utf-8")
    jd = (FIXTURES / "jd_backend.txt").read_text(encoding="utf-8")

    assert detect_input_swap(resume, jd) is None


def test_internship_during_school_is_not_an_anomaly():
    """在校期间实习是正常经历，不能误报。"""
    parsed = ResumeParsed(
        raw_text="张三\n2020.09-2024.06 某大学\n2023.07-2023.09 某公司 实习生",
        experiences=[
            Experience(id="intern_1", kind="intern", start="2023-07", end="2023-09"),
        ],
        education=[Education(school="某大学", start="2020-09", end="2024-06")],
    )
    text = "张三\n2020.09-2024.06 某大学\n2023.07-2023.09 某公司 实习生"

    assert detect_resume_anomalies(text, parsed) == []
