import json
from app.core.db import get_session, get_report, set_report_qa


def evaluate_answer(report_id: int, question: str, answer: str) -> str:
    with get_session() as session:
        report = get_report(session, report_id)
        if not report:
            return "未找到报告"

        # 简单的 Mock 点评逻辑（未来替换为 LLM 判断）
        if len(answer) < 10:
            comment = "点评：回答太短，缺乏具体细节，面试官会认为你在回避问题。"
        elif not any(char.isdigit() for char in answer) and "%" not in answer:
            comment = "点评：回答缺乏具体量化指标（无数字、无百分比），说服力不足。"
        else:
            comment = "点评：回答有一定的事实支撑，但建议进一步突出你个人的独立贡献。"

        # 获取旧的 QA 记录并追加
        qa_record = json.loads(report.qa) if report.qa else []
        qa_record.append({"question": question, "answer": answer, "comment": comment})

        # 用 C 同学写的函数更新数据库
        set_report_qa(session, report_id, json.dumps(qa_record, ensure_ascii=False))

        return comment