import streamlit as st
import requests

# 后端 API 基础地址
API_BASE = "http://127.0.0.1:8000/api"

st.set_page_config(layout="wide", page_title="简历诊断与模拟面试系统")
st.title("基于多Agent协作的简历诊断与模拟面试系统")

# 初始化 session state
if "report_id" not in st.session_state:
    st.session_state.report_id = None
if "rewrite_data" not in st.session_state:
    st.session_state.rewrite_data = None
if "qa_result" not in st.session_state:
    st.session_state.qa_result = {}

col1, col2, col3 = st.columns([1.2, 1.5, 1.5])

# ================= 第一栏：输入区 =================
with col1:
    st.header("📝 简历与JD输入")
    resume_text = st.text_area("简历纯文本", height=250)
    jd_text = st.text_area("目标岗位JD", height=150)

    if st.button("🚀 开始诊断", use_container_width=True):
        if len(resume_text) < 10 or len(jd_text) < 10:
            st.error("文本太短，请输入完整内容！")
        else:
            with st.spinner("Agent 1 正在解析简历与JD..."):
                try:
                    # 1. 调用 A 的解析接口
                    parse_res = requests.post(f"{API_BASE}/parse", json={
                        "resume_text": resume_text,
                        "jd_text": jd_text
                    })

                    if parse_res.status_code != 200:
                        st.error(f"解析失败：{parse_res.text}")
                        st.stop()

                    parse_data = parse_res.json()
                    # 提取 A 返回的解析结果（根据 A 的 Schema，可能是 parsed 和 req）
                    parsed_resume = parse_data.get("parsed", {})
                    req_jd = parse_data.get("req", {})

                except Exception as e:
                    st.error(f"连接解析接口失败：{e}")
                    st.stop()

            with st.spinner("Agent 2 正在进行匹配打分..."):
                try:
                    # 2. 调用 B 的匹配接口
                    match_res = requests.post(f"{API_BASE}/match", json={
                        "parsed": parsed_resume,
                        "req": req_jd
                    })

                    if match_res.status_code != 200:
                        st.error(f"匹配失败：{match_res.text}")
                        st.stop()

                    match_data = match_res.json()

                    # 3. 拿到最终的 report_id
                    # (注意：假设 B 的返回里包含了 report_id，如果没有，需要 B 补上)
                    report_id = match_data.get("report_id")
                    if not report_id:
                        st.error("匹配成功但未返回 report_id，请检查 B 的接口代码。")
                        st.stop()

                    st.session_state.report_id = report_id
                    st.session_state.rewrite_data = None
                    st.session_state.qa_result = {}
                    st.success("诊断完成！")

                except Exception as e:
                    st.error(f"连接匹配接口失败：{e}")

# ================= 第二栏：匹配与风险 =================
with col2:
    st.header("🔍 匹配分与风险拷问")
    if st.session_state.report_id:
        # 真实请求后端获取报告！
        try:
            res = requests.get(f"{API_BASE}/report/{st.session_state.report_id}")
            if res.status_code == 200:
                report = res.json()

                st.metric(label="综合匹配分", value=f"{report['score']} / 100")

                st.subheader("🔴 风险标红")
                for r in report['risks']:
                    st.markdown(
                        f"<span style='background-color:#ffe0e0; padding:2px; border-radius:4px;'>{r['text']}</span> - {r['reason']}",
                        unsafe_allow_html=True)

                st.subheader("☠️ 致命五问")
                # 从 risks 里提取问题
                questions = report['risks'][0].get('questions', []) if report['risks'] else []
                for i, q in enumerate(questions):
                    st.write(f"**Q{i + 1}:** {q}")
                    ans = st.text_input("回答", key=f"ans_{i}", label_visibility="collapsed")

                    if st.button("提交点评", key=f"btn_{i}"):
                        with st.spinner("点评中..."):
                            # 请求后端 QA 接口
                            qa_res = requests.post(f"{API_BASE}/qa", json={
                                "report_id": st.session_state.report_id,
                                "question": q,
                                "answer": ans
                            })
                            if qa_res.status_code == 200:
                                st.session_state.qa_result[i] = qa_res.json()['comment']

                    # 显示缓存的点评结果
                    if i in st.session_state.qa_result:
                        st.info(st.session_state.qa_result[i])
            else:
                st.error("未找到报告，请检查数据库是否有 ID 为 1 的数据。")
        except Exception as e:
            st.error("无法连接后端，请检查 uvicorn 是否在运行。")
    else:
        st.info("等待诊断结果...")

# ================= 第三栏：STAR 重写 =================
with col3:
    st.header("✨ STAR 重写")
    if st.session_state.report_id:
        if st.button("🪄 生成 STAR 重写"):
            with st.spinner("AI 正在重写..."):
                try:
                    # 真实请求后端重写接口
                    res = requests.post(f"{API_BASE}/rewrite", json={
                        "report_id": st.session_state.report_id,
                        "experience_id": "proj_1"
                    })
                    if res.status_code == 200:
                        st.session_state.rewrite_data = res.json()
                    else:
                        st.error("重写失败，未找到数据。")
                except Exception as e:
                    st.error("无法连接后端。")

        # 渲染重写结果
        if st.session_state.rewrite_data:
            rw = st.session_state.rewrite_data
            st.success(f"重写后预估得分: {rw['improved_score']} (提升明显)")
            st.text_area("修改前 (Before)", value=rw["before"], height=100, disabled=True)
            st.text_area("修改后 (After) - 可直接复制", value=rw["after"], height=250)
    else:
        st.info("等待重写结果...")