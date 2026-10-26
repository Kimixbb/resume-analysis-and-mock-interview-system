# backend/scripts/try_parse.py，在项目根目录运行（服务先起好）
import httpx
from pathlib import Path

d = Path(__file__).resolve().parents[1] / "fixtures"
r = httpx.post(
    "http://127.0.0.1:8000/api/parse",
    json={
        "resume_text": (d / "resume_bad.txt").read_text(encoding="utf-8"),
        "jd_text": (d / "jd_backend.txt").read_text(encoding="utf-8"),
    },
)
print(r.status_code, r.json())
