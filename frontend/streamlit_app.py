"""基于多 Agent 协作的简历诊断与模拟面试系统 —— Streamlit 单页前端。

这一页只做四件事：输入校验 → 调后端 7 个接口 → 展示诊断报告 → 承载问答/重写交互。

诊断链严格按设计文档 §2.1 执行：

    parse ──► （match ∥ interrogate） ──► POST /api/report ──► report_id
                                                   │
                              ┌────────────────────┴────────────────────┐
                              ▼                                         ▼
                       POST /api/qa（逐题）                     POST /api/rewrite

- report_id 只由 POST /api/report 产生，前端不臆造、也不从 match 的响应里拿；
- match 与 interrogate 用线程池并发，两段都成功后才落库；
- 刷新页面时从 URL 的 ?report_id= 恢复，调 GET /api/report/{id} 重渲染。
"""

from __future__ import annotations

import html as html_lib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
import streamlit as st

# 后端 API 基础地址；需要换端口时改这里或设环境变量 API_BASE
API_BASE = "http://127.0.0.1:8000/api"
TIMEOUT = 40  # 略大于后端 30s 的 LLM 超时，避免前端先断

RESUME_MIN, RESUME_MAX = 100, 8000
JD_MIN, JD_MAX = 50, 8000

st.set_page_config(layout="wide", page_title="简历诊断与模拟面试系统")


# ==================== 1. 通用小工具 ====================
class ApiError(Exception):
    """把后端的 {code, message} 或网络异常统一成前端可展示的一句话。"""

    def __init__(self, message: str, code: str = "NETWORK_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def api(method: str, path: str, payload: dict | None = None) -> dict:
    """调后端接口；HTTP 非 2xx 时抛出带中文提示的 ApiError。"""
    url = f"{API_BASE}{path}"
    try:
        response = requests.request(
            method, url, json=payload, timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        raise ApiError(f"无法连接后端（{url}），请确认 uvicorn 已启动。") from exc

    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("message") or body.get("detail") or response.text
        if not message:
            message = "请求失败，请重试"
        raise ApiError(str(message), str(body.get("code", response.status_code)))

    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("后端返回的不是合法 JSON") from exc


def truncate(text: str, limit: int) -> str:
    return text[:limit]


# 首行姓名 + `姓名：X` 两种写法；用于在发请求前拦住「两份简历拼在一起」
_NAME_LINE = re.compile(r"^([\u4e00-\u9fa5]{2,4})(?=\s*(?:[|｜]|$))", re.MULTILINE)
_NAME_LABEL = re.compile(r"姓\s*名\s*[：:]\s*([\u4e00-\u9fa5]{2,4})")
_STOPWORDS = {
    "教育经历", "工作经历", "实习经历", "项目经历", "校园经历", "项目经验",
    "工作经验", "个人信息", "求职意向", "自我评价", "个人评价", "专业技能",
    "技能", "证书", "获奖情况", "语言能力", "兴趣爱好", "联系方式", "个人项目",
    "基本信息", "教育背景", "工作背景",
    "获奖", "奖励", "荣誉", "项目", "证书", "培训", "专业", "语言", "兴趣",
    "联系", "基本", "教育", "工作", "实习", "校园", "个人", "自我", "求职",
    "经历", "技能", "特长", "爱好",
}


def detect_candidate_names(text: str) -> list[str]:
    """从简历文本里提取候选姓名（去重、按出现顺序）。"""
    names = [match.group(1) for match in _NAME_LABEL.finditer(text)]
    names += [
        match.group(1)
        for match in _NAME_LINE.finditer(text)
        if match.group(1) not in _STOPWORDS
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def reset_page_widgets() -> None:
    """新报告/清空时丢掉旧报告留下的输入框内容，避免串题。"""
    for key in list(st.session_state.keys()):
        if key == "rewrite_after" or key.startswith("qa_answer_"):
            del st.session_state[key]


def init_state() -> None:
    """一次性初始化 session_state，并尝试从 URL 恢复上一次的报告。"""
    defaults: dict[str, Any] = {
        "report": None,  # GET /api/report/{id} 的完整响应
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if st.session_state.report is not None:
        return
    raw_id = st.query_params.get("report_id")
    if raw_id:
        restore_report(raw_id)


def show_error(exc: Exception) -> None:
    """按错误码给出设计文档 §7.5 要求的话术。"""
    if isinstance(exc, ApiError):
        if exc.code in {"NOT_FOUND", "404"}:
            st.error("报告不存在，请重新诊断。")
            st.session_state.report = None
            st.query_params.clear()
            st.rerun()
            return
        if exc.code in {"LLM_OUTPUT_INVALID", "422"}:
            st.error("生成失败，请重试。")
            return
        if exc.code in {"LLM_UPSTREAM_ERROR", "DB_ERROR", "INTERNAL_ERROR", "500"}:
            st.error("服务超时 / 保存失败，请重试。")
            return
        st.error(exc.message)
        return
    st.error(f"出现未知错误：{exc}")


# ==================== 2. 诊断链：parse → (match ∥ interrogate) → report ====================
def run_diagnosis(resume_text: str, jd_text: str) -> dict:
    """按设计文档的并行链路跑完一次诊断，返回落库后的完整报告。"""
    resume_text = truncate(resume_text, RESUME_MAX)
    jd_text = truncate(jd_text, JD_MAX)

    with st.spinner("Agent 1 正在解析简历与 JD ..."):
        parsed = api("POST", "/parse", {"resume_text": resume_text, "jd_text": jd_text})

    with st.spinner("Agent 2 与 Agent 3 正在并行匹配、拷问 ..."):
        with ThreadPoolExecutor(max_workers=2) as pool:
            match_future = pool.submit(
                api, "POST", "/match", {"parsed": parsed["parsed"], "req": parsed["req"]}
            )
            interrogate_future = pool.submit(
                api,
                "POST",
                "/interrogate",
                {"parsed": parsed["parsed"], "req": parsed["req"]},
            )
            # 任何一个失败都会在 result() 处抛出，本次诊断就此终止
            match_data = match_future.result()
            interrogate_data = interrogate_future.result()

    with st.spinner("正在汇总落库 ..."):
        created = api(
            "POST",
            "/report",
            {
                "resume_text": resume_text,
                "jd_text": jd_text,
                "parsed": parsed["parsed"],
                "req": parsed["req"],
                "score": match_data["score"],
                "gaps": match_data["gaps"],
                "risks": interrogate_data["risks"],
                "questions": interrogate_data["questions"],
                "weakest_experience_id": interrogate_data.get("weakest_experience_id"),
            },
        )

    return api("GET", f"/report/{created['report_id']}")


def restore_report(raw_id: str) -> None:
    """刷新后按 URL 里的 report_id 回显；坏 id 清掉参数、回到输入态。"""
    try:
        report_id = int(raw_id)
    except (TypeError, ValueError):
        st.query_params.clear()
        return
    try:
        st.session_state.report = api("GET", f"/report/{report_id}")
    except Exception:  # 报告被删/库被清时不应白屏
        st.session_state.report = None
        st.query_params.clear()


def highlight(raw_text: str, risks: list[dict]) -> str:
    """把风险片段包成红底 HTML（与后端 render_highlighted 的展示口径一致）。"""
    spans: list[tuple[int, int]] = []
    for risk in risks:
        start = max(0, int(risk.get("start", 0)))
        end = min(len(raw_text), int(risk.get("end", 0)))
        if start < end:
            spans.append((start, end))
    if not spans:
        return html_lib.escape(raw_text).replace("\n", "<br>")

    cuts = {0, len(raw_text)}
    for start, end in spans:
        cuts.add(start)
        cuts.add(end)

    parts: list[str] = []
    ordered = sorted(cuts)
    for left, right in zip(ordered, ordered[1:]):
        segment = html_lib.escape(raw_text[left:right])
        if any(start <= left and right <= end for start, end in spans):
            segment = (
                '<span style="background:#ffe0e0;border-bottom:2px solid #e05252">'
                f"{segment}</span>"
            )
        parts.append(segment)
    return "".join(parts).replace("\n", "<br>")


# ==================== 3. 页面：左栏输入 ====================
init_state()

col_input, col_report, col_action = st.columns([1.1, 1.9, 1.2])

with col_input:
    st.header("📝 简历与 JD 输入")
    resume_text = st.text_area("简历纯文本", height=260, key="resume_input")
    jd_text = st.text_area("目标岗位 JD", height=160, key="jd_input")

    if st.button(
        "🚀 开始诊断", use_container_width=True, type="primary", key="diagnose_button"
    ):
        resume_clean = resume_text.strip()
        jd_clean = jd_text.strip()
        if len(resume_clean) < RESUME_MIN:
            st.error(f"简历太短：至少 {RESUME_MIN} 字（当前 {len(resume_clean)} 字）")
        elif len(jd_clean) < JD_MIN:
            st.error(f"JD 太短：至少 {JD_MIN} 字（当前 {len(jd_clean)} 字）")
        elif len(detect_candidate_names(resume_clean)) >= 2:
            names = detect_candidate_names(resume_clean)
            st.error(
                f"检测到多个姓名（{'、'.join(names)}），这看起来是两份简历拼在一起。"
                "请只提交一位候选人的简历。"
            )
        else:
            try:
                report = run_diagnosis(resume_clean, jd_clean)
                reset_page_widgets()
                st.session_state.report = report
                st.query_params["report_id"] = str(report["report_id"])
                st.success("诊断完成，报告已保存。")
            except Exception as exc:
                st.session_state.report = None
                show_error(exc)

    if st.button("🧹 清空当前报告", use_container_width=True, key="clear_button"):
        reset_page_widgets()
        st.session_state.report = None
        st.query_params.clear()
        st.rerun()

report = st.session_state.report

# ==================== 4. 中栏：分数、差距、标红、追问 ====================
with col_report:
    st.header("🔍 匹配分与风险拷问")
    if report is None:
        st.info("等待诊断结果 ...")
    else:
        st.metric(label="综合匹配分", value=f"{report['score']} / 100")

        st.subheader("📉 三条关键差距")
        for index, gap in enumerate(report["gaps"], start=1):
            st.markdown(f"**{index}. {gap['jd']}**")
            st.caption(f"简历证据：{gap['resume']}")
            st.write(gap["detail"])

        st.subheader("🔴 风险标红（简历原文）")
        st.markdown(
            f"<div style='line-height:1.9;border:1px solid #eee;"
            f"border-radius:8px;padding:12px;max-height:320px;overflow:auto'>"
            f"{highlight(report['resume_text'], report['risks'])}</div>",
            unsafe_allow_html=True,
        )
        for risk in report["risks"]:
            st.markdown(f"- **[{risk['type']}]** {risk['text']} —— {risk['reason']}")

# ==================== 5. 右栏：逐题问答 + STAR 重写 ====================
with col_action:
    st.header("☠️ 致命追问")
    questions = report["questions"] if report else []
    if report is None:
        st.info("等待诊断结果 ...")
    elif not questions:
        st.success("未发现致命问题 ✅")
    else:
        answered = {entry["question_index"]: entry for entry in (report.get("qa") or [])}
        current = next((i for i in range(len(questions)) if i not in answered), None)

        # 已答的题目：显示问题 + 点评
        for index in sorted(answered):
            entry = answered[index]
            st.markdown(f"**Q{index + 1}. {entry['question']}**")
            st.caption(f"你的回答：{entry['answer']}")
            st.info(entry["comment"])

        if current is None:
            st.success("全部题目已答完 🎉")
        else:
            question = questions[current]
            st.markdown(
                f"**Q{current + 1} / {len(questions)}. {question['text']}**"
            )
            with st.form(key=f"qa_form_{current}"):
                answer = st.text_area(
                    "你的回答",
                    height=110,
                    placeholder="用具体事实回答：背景、你的动作、可验证的结果 ...",
                    key=f"qa_answer_{current}",
                )
                submitted = st.form_submit_button("提交点评", use_container_width=True)

            if submitted:
                if not answer.strip():
                    st.warning("回答不能为空。")
                else:
                    try:
                        result = api(
                            "POST",
                            "/qa",
                            {
                                "report_id": report["report_id"],
                                "question_index": current,
                                "answer": answer.strip(),
                            },
                        )
                        # 提交后重新拉一次报告，问答/重写状态以数据库为准
                        st.session_state.report = api(
                            "GET", f"/report/{report['report_id']}"
                        )
                        st.success(result["comment"])
                        st.rerun()
                    except Exception as exc:
                        show_error(exc)

    st.divider()
    st.header("✨ STAR 重写")
    if report is None:
        st.info("等待诊断结果 ...")
    elif st.button("🪄 生成 STAR 重写", use_container_width=True, key="rewrite_button"):
        try:
            with st.spinner("AI 正在重写最差经历 ..."):
                api(
                    "POST",
                    "/rewrite",
                    {"report_id": report["report_id"]},
                )
            st.session_state.report = api("GET", f"/report/{report['report_id']}")
            st.rerun()
        except Exception as exc:
            show_error(exc)

    if report is not None and report.get("rewrite"):
        rewrite = report["rewrite"]
        st.success(f"重写后预估得分：{rewrite['improved_score']}（原 {report['score']}）")
        with st.expander("改前（简历原文）", expanded=False):
            st.text(rewrite["before"])
        st.text_area(
            "改后（可直接复制）",
            value=rewrite["after"],
            height=240,
            key="rewrite_after",
        )
        st.caption(
            " | ".join(
                f"{key}：{value}" for key, value in rewrite["star"].items()
            )
        )
