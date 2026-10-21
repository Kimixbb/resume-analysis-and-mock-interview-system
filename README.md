# 基于多Agent协作的简历诊断与模拟面试系统

组名：诊断面试官小组
技术栈：Python 3.13 + FastAPI + Streamlit + SQLite + SQLAlchemy + OpenAI 兼容 LLM 接口

## 架构
- 前端：Streamlit 单页 → frontend/streamlit_app.py
- 后端：FastAPI 7 接口 → backend/app/main.py（从 backend/ 目录启动）
- 数据：SQLite 3 表（resume/jd/report）→ backend/app/core/db.py + models.py
- 接口契约以 docs/02-设计文档.md 第 5 节为准（先看这个再写代码）

## 模块归属（看这张表就知道代码放哪）
| 模块 | 负责人 | 代码位置（routers/ + services/ + contracts/，按 02 文档命名规范自建） | 接口 | 单元测试 |
|------|--------|----------|------|----------|
| M1 解析 | A（组长） | parse 相关文件 | POST /api/parse | backend/tests/ |
| M2 匹配 | B | match 相关文件 | POST /api/match | backend/tests/ |
| M3 拷问 | C | interrogate 相关文件；维护 core/ 平台骨架（llm/db/config/errors） | POST /api/interrogate | backend/tests/ |
| M4 重写+前端+存库 | D | report / rewrite / qa 相关文件、frontend/ | POST /api/report、GET /api/report/{id}、POST /api/rewrite、POST /api/qa | backend/tests/ |
| 全链路集成 | D（测试负责人） | — | parse→match/interrogate(并行)→report→rewrite/qa | backend/tests/ |

## 文档归属（docs/）
| 文档 | 负责人 |
|------|--------|
| 00-文档模板 | A |
| 01-需求文档 | B |
| 02-设计文档 | C |
| 03-测试文档 / 04-用户说明 | D |
| 20-进度表 / 答辩材料 | A |

## 快速开始
```bash
# 配置：复制 .env.example 为 .env，填上 API Key、模型等
cp .env.example .env
pip install -r requirements.txt

# 后端（终端1）
cd backend
python -m uvicorn app.main:app --reload

# 前端（终端2）
streamlit run frontend/streamlit_app.py

# 单元测试
pytest
```

## 分支约定
- main 分支随时可用；各人开发在自己分支 `feature/Mx-姓名`
- 自测通过直接 merge 回 main；小改动可直接推 main
- 文档修改：直接改文件 + 群里说一声，版本号 +0.1
