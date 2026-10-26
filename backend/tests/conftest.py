"""pytest 共享配置：让测试能 import app 包。

配置（API Key、模型名、数据库地址）不在这里伪造，测试直接依赖
项目根目录的 .env——和正式运行用的是同一份配置。
所有会真正调用 LLM 的测试都必须用 monkeypatch 替换掉 model_json，
所以 .env 里哪怕还是占位符、没填真实 Key，测试也能全绿、不联网。
"""

import sys
from pathlib import Path

# conftest.py 位于 backend/tests/，parents[1] 就是 backend/。
# 把 backend/ 加进 sys.path，测试文件里才能 import app.xxx。
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# app.core.config 在被 import 时就会读取 .env，缺了会报一长串看不懂的
# pydantic 校验错误，所以在这里提前检查，缺了就给出一句人话提示。
ENV_FILE = BACKEND_DIR.parent / ".env"  # 项目根目录下的 .env
if not ENV_FILE.exists():
    raise SystemExit(
        "测试需要项目根目录下的 .env 文件：\n"
        "请先把 .env.example 复制为 .env（占位值即可，测试不会真的调 LLM），"
        "然后再运行 pytest。"
    )
