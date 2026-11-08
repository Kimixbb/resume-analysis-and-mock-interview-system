"""M4 输入一致性校验：拒绝「两份简历混在一起」或「简历/JD 填反」的脏数据落库。

设计背景：M1 只负责抽取、M2 只负责打分、M3 的风险类型只覆盖
「空话 / 无数字 / 日期倒置」，所以把两个人的简历拼在一起、或者把简历和
JD 填反时，整条链路仍会把它当成正常输入，打出看似正常的分。

M4 是落库前的最后一道关，这里做确定性的输入校验：
1. 简历框里出现「岗位职责/任职要求」等 JD 文本、JD 框里出现履历/日期/联系方式
   → 判定为「简历和 JD 填反了」；
2. 文本里出现多个姓名（首行姓名、`姓名：X` 两种写法）；
3. 全职工作与实习时间重叠；
4. 在校时间与全职工作重叠；
5. 自称「应届」但存在 2 年以上的全职经历。

发现异常 → `POST /api/report` 返回 400 `INVALID_INPUT`，并说明原因；
不改变 M1/M2/M3 的契约，也不依赖 LLM。
"""

from __future__ import annotations

import re
from datetime import date

from app.contracts.parse import ResumeParsed

# 首行姓名：2–4 个汉字，后面紧接 `|`/`｜` 或行尾
_NAME_LINE = re.compile(r"^([\u4e00-\u9fa5]{2,4})(?=\s*(?:[|｜]|$))", re.MULTILINE)
# `姓名：张三` / `姓 名: 张三`
_NAME_LABEL = re.compile(r"姓\s*名\s*[：:]\s*([\u4e00-\u9fa5]{2,4})")

# 判定「这段文本像 JD」的强特征
_JD_MARKERS = (
    "岗位职责", "任职要求", "岗位要求", "任职资格", "职位描述",
    "岗位描述", "招聘", "工作内容", "薪资", "福利", "简历投递",
)
# 判定「这段文本像简历」的强特征
_RESUME_MARKERS = (
    "求职意向", "教育经历", "工作经历", "实习经历", "项目经历",
    "校园经历", "项目经验", "姓名", "电话", "邮箱", "毕业院校", "主修",
)
_DATE_RANGE = re.compile(
    r"\d{4}\s*[.\-/年]\s*\d{1,2}\s*[-–—~至]\s*(?:\d{4}\s*[.\-/年]\s*\d{1,2}|至今|现在)"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"1[3-9]\d{9}|\d{3,4}-\d{7,8}")

# 这些是栏目名，不是姓名
_STOPWORDS = {
    "教育经历", "工作经历", "实习经历", "项目经历", "校园经历", "项目经验",
    "工作经验", "个人信息", "求职意向", "自我评价", "个人评价", "专业技能",
    "技能", "证书", "获奖情况", "语言能力", "兴趣爱好", "联系方式", "个人项目",
    "基本信息", "教育背景", "工作背景",
    "获奖", "奖励", "荣誉", "项目", "证书", "培训", "专业", "语言", "兴趣",
    "联系", "基本", "教育", "工作", "实习", "校园", "个人", "自我", "求职",
    "经历", "技能", "特长", "爱好",
}

_PRESENT_WORDS = ("至今", "现在", "present", "now", "今")


def _month(value: str | None) -> int | None:
    """把 2023-07 / 2023.07 / 2023年7月 统一成 202307；解析不了返回 None。"""
    if not value:
        return None
    match = re.search(r"(\d{4})\D{0,2}(\d{1,2})", value)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return year * 100 + month


def _span(experience) -> tuple[int, int] | None:
    """取一段经历的时间区间；没有开始时间、或只有开始没有结束时返回 None。"""
    start = _month(experience.start)
    if start is None:
        return None

    end_text = (experience.end or "").strip()
    if any(word in end_text.lower() for word in _PRESENT_WORDS):
        end = 999912
    else:
        end = _month(experience.end)
    if end is None:
        return None
    if end < start:
        # 起止倒置属于 M3 的规则，这里不重复报
        return None
    return start, end


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """两个 [start, end] 区间是否有交集（按年月）。"""
    return max(a[0], b[0]) < min(a[1], b[1])


def _fmt(span: tuple[int, int]) -> str:
    start, end = span
    end_text = "至今" if end == 999912 else f"{end // 100:04d}-{end % 100:02d}"
    return f"{start // 100:04d}-{start % 100:02d}–{end_text}"


def detect_input_swap(resume_text: str, jd_text: str) -> str | None:
    """简历框里放的是 JD、JD 框里放的是简历时，返回提示文案；正常返回 None。"""
    jd_hits = [marker for marker in _JD_MARKERS if marker in resume_text]
    if len(jd_hits) < 2:
        return None

    resume_hits = [marker for marker in _RESUME_MARKERS if marker in jd_text]
    looks_like_resume = (
        bool(_DATE_RANGE.search(jd_text))
        or bool(_EMAIL.search(jd_text))
        or bool(_PHONE.search(jd_text))
    )
    if not (len(resume_hits) >= 2 or (resume_hits and looks_like_resume)):
        return None

    return (
        "简历和 JD 可能填反了：简历框里出现「"
        + "、".join(jd_hits[:3])
        + "」等岗位描述，JD 框里出现履历/日期/联系方式等简历内容。"
        "请交换两个输入框后重试。"
    )


def detect_candidate_names(resume_text: str) -> list[str]:
    """从简历文本里提取候选姓名（去重、按出现顺序）。"""
    names: list[str] = []
    for match in _NAME_LABEL.finditer(resume_text):
        names.append(match.group(1))
    for match in _NAME_LINE.finditer(resume_text):
        name = match.group(1)
        if name not in _STOPWORDS:
            names.append(name)

    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def detect_resume_anomalies(resume_text: str, parsed: ResumeParsed) -> list[str]:
    """返回「这份简历可能不是同一个人」的具体原因；空列表表示没发现问题。"""
    anomalies: list[str] = []

    names = detect_candidate_names(resume_text)
    if len(names) >= 2:
        anomalies.append(f"出现多个姓名（{'、'.join(names)}）")

    experiences = list(parsed.experiences)
    works = [
        (exp, span)
        for exp in experiences
        if exp.kind == "work"
        for span in [_span(exp)]
        if span is not None
    ]
    interns = [
        (exp, span)
        for exp in experiences
        if exp.kind == "intern"
        for span in [_span(exp)]
        if span is not None
    ]

    # 全职与实习时间重叠
    for work, work_span in works:
        for intern, intern_span in interns:
            if _overlap(work_span, intern_span):
                anomalies.append(
                    "全职工作与实习时间重叠"
                    f"（{work.title or '全职'} {_fmt(work_span)} / "
                    f"{intern.title or '实习'} {_fmt(intern_span)}）"
                )
                break
        else:
            continue
        break

    # 在校时间与全职工作重叠
    for education in parsed.education:
        edu_start = _month(education.start)
        edu_end = _month(education.end)
        if edu_start is None or edu_end is None or edu_end < edu_start:
            continue
        for work, work_span in works:
            if _overlap((edu_start, edu_end), work_span):
                anomalies.append(
                    "在校时间与全职工作重叠"
                    f"（{education.school or '在校'} {_fmt((edu_start, edu_end))} / "
                    f"{work.title or '全职'} {_fmt(work_span)}）"
                )
                break
        else:
            continue
        break

    # 自称应届，但有 2 年以上的全职经历
    if "应届" in resume_text:
        cutoff = (date.today().year - 2) * 100 + date.today().month
        if any(work_span[0] <= cutoff for _work, work_span in works):
            anomalies.append("简历自称「应届」，但存在 2 年以上的全职工作经历")

    return anomalies
