"""M4 数据层（负责人：D）
职责：SQLite 建 3 张表并读写：
     resume(id, raw_text, parsed_json)
     jd(id, raw_text, parsed_json)
     report(id, resume_id, jd_id, 各阶段json, composite_score)
契约：见 docs/10-接口契约.md 的 3张表 小节；数据库文件 data/*.sqlite（已gitignore）
"""


def init_db() -> None:
    """TODO(D): 建库建表"""
    pass
