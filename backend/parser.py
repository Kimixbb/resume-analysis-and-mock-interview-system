"""M1 解析模块（负责人：A组长）
职责：简历/JD结构化抽取；NER+LLM+正则三步校验；时间重叠检查
契约：见 docs/10-接口契约.md 的 /parse 小节；接口文档 docs/11-接口文档-M1.md
"""


def handle(payload: dict) -> dict:
    """TODO(A): 实现 POST /parse 业务逻辑；收 resume_text（必填）、jd_text（选填）"""
    return {"todo": "M1 not implemented"}
