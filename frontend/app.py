"""M4 前端（负责人：D）：Streamlit 单页 三栏布局占位
运行：streamlit run frontend/app.py
"""
import streamlit as st

st.set_page_config(page_title="简历压力测试与模拟面试", page_icon="📄")
st.title("📄 简历压力测试与模拟面试系统")

left, mid, right = st.columns([1, 1, 1])
left.subheader("① 输入")
left.caption("TODO(D)：简历上传/JD粘贴")
mid.subheader("② 诊断")
mid.caption("TODO(D)：匹配分+差距清单+致命问")
right.subheader("③ STAR重写")
right.caption("TODO(D)：原版vs优化版对比")
