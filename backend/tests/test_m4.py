import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# 导入你的 FastAPI app
from app.main import app

client = TestClient(app)

# ================= 测试数据准备 =================
MOCK_REPORT = {
    "id": 1,
    "resume_id": 1,
    "jd_id": 1,
    "score": 62,
    "gaps": [{"jd": "高并发", "resume": "单体", "detail": "缺并发经验"}],
    "risks": [{"type": "无数字", "text": "大幅提升", "reason": "无基线"}],
    "qa": None,
    "rewrite": None
}


# ================= 1. 测试 GET /api/report/{id} =================
# 我们 mock 掉底层的 get_report_by_id 函数，不让它真去查数据库
@patch("app.services.report_service.get_report_by_id")
def test_get_report_success(mock_get):
    # 强制让它返回我们准备好的假数据
    mock_get.return_value = MOCK_REPORT

    response = client.get("/api/report/1")

    assert response.status_code == 200
    assert response.json()["score"] == 62
    assert len(response.json()["gaps"]) == 1


@patch("app.services.report_service.get_report_by_id")
def test_get_report_not_found(mock_get):
    # 模拟数据库中找不到数据的情况
    mock_get.return_value = None

    response = client.get("/api/report/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "报告不存在"


# ================= 2. 测试 POST /api/rewrite =================
@patch("app.services.rewrite_service.generate_star_rewrite")
def test_rewrite_success(mock_rewrite):
    # 模拟大模型返回的重写结果
    mock_rewrite.return_value = {
        "before": "负责后端开发",
        "after": "[S] 负责订单服务... [R] P99降至210ms",
        "star": {"S": "情境", "T": "任务", "A": "行动", "R": "结果"},
        "improved_score": 78
    }

    response = client.post("/api/rewrite", json={"report_id": 1, "experience_id": "exp_1"})

    assert response.status_code == 200
    data = response.json()
    assert data["improved_score"] == 78
    assert "after" in data
    assert "star" in data


# ================= 3. 测试 POST /api/qa =================
@patch("app.services.qa_service.evaluate_answer")
def test_qa_success(mock_qa):
    # 模拟大模型的点评结果
    mock_qa.return_value = "点评：回答缺乏具体量化指标。"

    response = client.post("/api/qa", json={
        "report_id": 1,
        "question": "优化前QPS是多少？",
        "answer": "大概快了很多"
    })

    assert response.status_code == 200
    assert response.json()["comment"] == "点评：回答缺乏具体量化指标。"