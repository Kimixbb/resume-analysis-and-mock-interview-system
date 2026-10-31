import json
from app.core.db import get_session, get_report, set_report_rewrite


def generate_star_rewrite(report_id: int, experience_id: str = "proj_1") -> dict:
    with get_session() as session:
        report = get_report(session, report_id)
        if not report:
            return None

        risks = json.loads(report.risks)
        # TODO: 实际应从 resume 关联表获取原文本，这里先 Mock 一段坏文本
        before_text = "负责后端开发，大幅提升了系统性能，获得一致好评。"

        # 这里未来需要接入 C 同学写好的 llm_client
        # 现在的返回结果是 Mock（模拟大模型的输出）
        mock_result = {
            "before": before_text,
            "after": "[S] 负责订单服务性能优化。[T] 独立承担接口层重构。[A] 定位到N+1查询，引入Redis缓存热点商品。[R] 上线后P99降至210ms（↓74%），QPS从300提升至1200。",
            "star": {
                "S": "订单服务性能优化",
                "T": "独立承担接口层重构",
                "A": "引入Redis缓存，合并批量查询",
                "R": "P99降至210ms，QPS提升至1200"
            },
            "improved_score": min(100, report.score + 15)
        }

        # 用 C 同学写的函数更新数据库
        set_report_rewrite(session, report_id, json.dumps(mock_result, ensure_ascii=False))

        return mock_result