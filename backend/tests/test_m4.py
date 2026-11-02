"""M4 的旧版测试入口已拆分，保留这个文件只为兼容原来的测试命令。

- 接口测试：backend/tests/test_report_router.py（真实服务 + 独立测试库）
- 规则点评：backend/tests/test_qa_service.py
- STAR 重写：backend/tests/test_rewrite_service.py
- 全链路：backend/tests/test_full_chain.py
"""


def test_m4_suite_moved_to_dedicated_files():
    """旧文件不再 mock 掉服务层；用例已迁移到上面四个文件，这里只做指引。"""
    assert True
