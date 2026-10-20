# 基于多Agent对抗的简历压力测试与模拟面试系统

组名：诊断面试官小组
技术栈：Python 3.13 + FastAPI + Streamlit + SQLite + DeepSeek

## 架构
- 前端：Streamlit 单页（左输入/中诊断/右重写）→ frontend/app.py
- 后端：FastAPI 4接口 → backend/main.py
- 数据：SQLite 3表（resume/jd/report）→ backend/db.py
- 接口职责契约：docs/10-接口契约.md（先看这个再写代码）

## 模块归属（看这张表就知道代码放哪）
| 模块 | 负责人 | 代码文件 | 接口 | 单元测试 |
|------|--------|----------|------|----------|
| M1 解析 | A（组长） | backend/parser.py | POST /parse | tests/test_parser.py |
| M2 匹配 | B | backend/matcher.py | POST /match | tests/test_matcher.py |
| M3 拷问 | C | backend/interrogator.py | POST /interrogate | tests/test_interrogator.py |
| M4 重构+前端+存库 | D | backend/rewriter.py、frontend/app.py、backend/db.py | POST /rewrite | tests/test_rewriter.py |
| 全链路集成 | D（测试负责人） | — | parse→match→interrogate→rewrite | tests/test_integration.py |

## 文档归属（docs/）
| 文档 | 负责人 |
|------|--------|
| 00-文档模板 | A |
| 01-需求文档 | B |
| 02-设计文档 | C |
| 03-测试文档 / 04-用户说明 | D |
| 10-接口契约 / 20-进度表 / 答辩材料 | A |
| 11~14 各模块接口文档 | 各人写自己模块 |

## 快速开始
```bash
pip install -r requirements.txt

# 后端（终端1）
uvicorn backend.main:app --reload

# 前端（终端2）
streamlit run frontend/app.py

# 单元测试
pytest
```

## 分支约定
- main 分支随时可用；各人开发在自己分支 `feature/Mx-姓名`
- 自测通过直接 merge 回 main；小改动可直接推 main
- 文档修改：直接改文件 + 群里说一声，版本号 +0.1
